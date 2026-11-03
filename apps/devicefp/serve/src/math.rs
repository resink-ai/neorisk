//! CPU kernels: GEMM through the `gemm` crate, everything else as plain loops compiled per SIMD
//! level by `multiversion` and picked at run time (AVX-512, AVX2+FMA, or baseline SSE2).

use multiversion::multiversion;

/// c[m x n] (+)= a[m x k] * b[k x n], all row-major with leading dimensions (in elements).
#[allow(clippy::too_many_arguments)]
pub fn matmul(
    m: usize,
    n: usize,
    k: usize,
    a: &[f32],
    lda: usize,
    b: &[f32],
    ldb: usize,
    c: &mut [f32],
    ldc: usize,
    accumulate: bool,
    threads: usize,
) {
    if m == 0 {
        return;
    }
    assert!(
        a.len() >= (m - 1) * lda + k
            && b.len() >= (k - 1) * ldb + n
            && c.len() >= (m - 1) * ldc + n
    );
    let par = if threads > 1 {
        gemm::Parallelism::Rayon(threads)
    } else {
        gemm::Parallelism::None
    };
    // SAFETY: the asserts above keep every strided access inside the slices.
    unsafe {
        gemm::gemm(
            m,
            n,
            k,
            c.as_mut_ptr(),
            1,
            ldc as isize,
            accumulate,
            a.as_ptr(),
            1,
            lda as isize,
            b.as_ptr(),
            1,
            ldb as isize,
            1.0f32,
            1.0f32,
            false,
            false,
            false,
            par,
        );
    }
}

/// Adds `bias` to every row of `x` (rows of length bias.len(), stride ld); optionally ReLU after.
#[multiversion(targets = "simd")]
pub fn add_bias(x: &mut [f32], ld: usize, bias: &[f32], relu: bool) {
    let n = bias.len();
    for row in x.chunks_mut(ld) {
        let row = &mut row[..n];
        if relu {
            for (v, b) in row.iter_mut().zip(bias) {
                *v = (*v + *b).max(0.0);
            }
        } else {
            for (v, b) in row.iter_mut().zip(bias) {
                *v += *b;
            }
        }
    }
}

/// out = LayerNorm(x) row by row (biased variance, like torch).
#[multiversion(targets = "simd")]
pub fn layer_norm(x: &[f32], out: &mut [f32], w: &[f32], b: &[f32], eps: f32) {
    let d = w.len();
    for (xr, or) in x.chunks_exact(d).zip(out.chunks_exact_mut(d)) {
        let mean = xr.iter().sum::<f32>() / d as f32;
        let var = xr.iter().map(|v| (v - mean) * (v - mean)).sum::<f32>() / d as f32;
        let r = 1.0 / (var + eps).sqrt();
        for i in 0..d {
            or[i] = (xr[i] - mean) * r * w[i] + b[i];
        }
    }
}

/// Like `layer_norm` but over rows `stride` elements apart (the CLS rows of a batch).
pub fn layer_norm_strided(
    x: &[f32],
    stride: usize,
    rows: usize,
    out: &mut [f32],
    w: &[f32],
    b: &[f32],
    eps: f32,
) {
    let d = w.len();
    for r in 0..rows {
        layer_norm(
            &x[r * stride..r * stride + d],
            &mut out[r * d..(r + 1) * d],
            w,
            b,
            eps,
        );
    }
}

/// expf to about 1 ulp (Cephes polynomial), branch-free so it vectorises.
#[inline(always)]
#[allow(clippy::excessive_precision)] // Cephes coefficients as published
pub fn exp(x: f32) -> f32 {
    const MAGIC: f32 = 12_582_912.0; // 1.5 * 2^23: adding and subtracting rounds to nearest
    let x = x.clamp(-87.3, 88.3);
    let n = (x * std::f32::consts::LOG2_E + MAGIC) - MAGIC;
    let r = x - n * 0.693_359_4 - n * -2.121_944_4e-4;
    let mut p = 1.987_569_1e-4f32;
    p = p * r + 1.398_199_9e-3;
    p = p * r + 8.333_452e-3;
    p = p * r + 4.166_579_6e-2;
    p = p * r + 1.666_666_5e-1;
    p = p * r + 5.000_000_1e-1;
    let y = p * r * r + r + 1.0;
    y * f32::from_bits(((n as i32 + 127) << 23) as u32)
}

/// Softmax of one row in place. Max and sum use 8 independent lanes so the loops vectorise
/// (a single running float reduction would force scalar code).
#[inline(always)]
fn softmax(s: &mut [f32]) {
    let mut m8 = [f32::NEG_INFINITY; 8];
    let (chunks, rest) = s.as_chunks::<8>();
    for c in chunks {
        for i in 0..8 {
            m8[i] = m8[i].max(c[i]);
        }
    }
    let m = rest
        .iter()
        .chain(&m8)
        .fold(f32::NEG_INFINITY, |a, &b| a.max(b));
    for v in s.iter_mut() {
        *v = exp(*v - m);
    }
    let mut s8 = [0f32; 8];
    let (chunks, rest) = s.as_chunks::<8>();
    for c in chunks {
        for i in 0..8 {
            s8[i] += c[i];
        }
    }
    let inv = 1.0 / (rest.iter().sum::<f32>() + s8.iter().sum::<f32>());
    for v in s.iter_mut() {
        *v *= inv;
    }
}

#[multiversion(targets = "simd")]
fn softmax_rows(s: &mut [f32], l: usize) {
    for row in s.chunks_exact_mut(l) {
        softmax(row);
    }
}

/// Self-attention over every token of `profiles` sequences of length `l`.
/// `qkv` rows are [q | k | v] (width 3d); `out` rows are the concatenated heads (width d).
/// `s` is scratch of at least l*l elements. Per head: S = Q K^T / sqrt(dh) and O = softmax(S) V
/// as two strided GEMMs reading the head's columns in place.
#[allow(clippy::too_many_arguments)]
pub fn attention_full(
    qkv: &[f32],
    profiles: usize,
    l: usize,
    d: usize,
    heads: usize,
    out: &mut [f32],
    s: &mut [f32],
) {
    let dh = d / heads;
    let scale = 1.0 / (dh as f32).sqrt();
    let w = 3 * d;
    assert!(qkv.len() >= profiles * l * w && out.len() >= profiles * l * d && s.len() >= l * l);
    for p in 0..profiles {
        let base = p * l * w;
        for h in 0..heads {
            let q = qkv[base + h * dh..].as_ptr();
            let k = qkv[base + d + h * dh..].as_ptr();
            let v = qkv[base + 2 * d + h * dh..].as_ptr();
            let o = out[p * l * d + h * dh..].as_mut_ptr();
            // SAFETY: the assert above bounds every row (stride w or d) of these l x dh blocks.
            unsafe {
                // S[l x l] = scale * Q[l x dh] * K^T[dh x l]   (K^T: row stride 1, column stride w)
                gemm::gemm(
                    l,
                    l,
                    dh,
                    s.as_mut_ptr(),
                    1,
                    l as isize,
                    false,
                    q,
                    1,
                    w as isize,
                    k,
                    w as isize,
                    1,
                    0.0f32,
                    scale,
                    false,
                    false,
                    false,
                    gemm::Parallelism::None,
                );
            }
            softmax_rows(&mut s[..l * l], l);
            unsafe {
                // O[l x dh] = P[l x l] * V[l x dh], written into this head's columns of `out`
                gemm::gemm(
                    l,
                    dh,
                    l,
                    o,
                    1,
                    d as isize,
                    false,
                    s.as_ptr(),
                    1,
                    l as isize,
                    v,
                    1,
                    w as isize,
                    0.0f32,
                    1.0f32,
                    false,
                    false,
                    false,
                    gemm::Parallelism::None,
                );
            }
        }
    }
}

/// Attention of one query per profile (the CLS token) over that profile's `l` keys.
/// `q` is profiles x d, `kv` rows are [k | v] (width 2d), `out` is profiles x d.
#[multiversion(targets = "simd")]
#[allow(clippy::too_many_arguments)]
pub fn attention_one(
    q: &[f32],
    kv: &[f32],
    profiles: usize,
    l: usize,
    d: usize,
    heads: usize,
    out: &mut [f32],
    s: &mut [f32],
) {
    let dh = d / heads;
    let scale = 1.0 / (dh as f32).sqrt();
    let w = 2 * d;
    for p in 0..profiles {
        for h in 0..heads {
            let qh = &q[p * d + h * dh..][..dh];
            let s = &mut s[..l];
            for (j, sj) in s.iter_mut().enumerate() {
                let k = &kv[(p * l + j) * w + h * dh..][..dh];
                *sj = qh.iter().zip(k).map(|(a, b)| a * b).sum::<f32>() * scale;
            }
            softmax(s);
            let o = &mut out[p * d + h * dh..][..dh];
            o.fill(0.0);
            for j in 0..l {
                let v = &kv[(p * l + j) * w + d + h * dh..][..dh];
                let pj = s[j];
                for c in 0..dh {
                    o[c] += pj * v[c];
                }
            }
        }
    }
}

/// Rows of `x` (width n) scaled to unit length (torch F.normalize, eps 1e-12), then by `scale`.
pub fn normalize_rows(x: &mut [f32], n: usize, scale: f32) {
    for row in x.chunks_exact_mut(n) {
        let norm = row.iter().map(|v| v * v).sum::<f32>().sqrt().max(1e-12);
        let k = scale / norm;
        for v in row.iter_mut() {
            *v *= k;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exp_matches_std() {
        let mut worst = 0f32;
        let mut x = -87.0f32;
        while x < 20.0 {
            let rel = ((exp(x) - x.exp()) / x.exp()).abs();
            worst = worst.max(rel);
            x += 0.0137;
        }
        assert!(worst < 3e-7, "worst relative error {worst}");
    }

    #[test]
    fn matmul_small() {
        let a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]; // 2x3
        let b = [1.0, 0.0, 0.0, 1.0, 1.0, 1.0]; // 3x2
        let mut c = [10.0; 4];
        matmul(2, 2, 3, &a, 3, &b, 2, &mut c, 2, false, 1);
        assert_eq!(c, [4.0, 5.0, 10.0, 11.0]);
        matmul(2, 2, 3, &a, 3, &b, 2, &mut c, 2, true, 1);
        assert_eq!(c, [8.0, 10.0, 20.0, 22.0]);
    }
}

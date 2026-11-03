//! int8 GEMM for the CPU recall study: y = (q(x) q(W)) * s_x * s_w + bias.
//!
//! Activations are quantised per row and weights per output column, symmetric to [-127, 127].
//! Values are held as i16 so AVX2 `vpmaddwd` (16 multiply-adds per instruction, exact into i32)
//! does the work; CPUs with AVX512-VNNI or AMX have faster int8 instructions that this kernel does
//! not use. Sums stay below 2^31 for k <= 2^16.

#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

/// Columns per packed block (two AVX2 registers of i32 sums).
const NR: usize = 16;

/// One linear layer's weights, quantised and packed for [`qgemm`].
pub struct QLin {
    pub n: usize,
    pub k: usize,
    /// per column block, per k pair: 16 columns x (w[2p][j], w[2p+1][j])
    packed: Vec<i16>,
    pub scale: Vec<f32>,
}

impl QLin {
    /// `w` is k x n row-major with leading dimension `ldw` (a column slice of a wider matrix).
    pub fn new(w: &[f32], ldw: usize, k: usize, n: usize) -> Self {
        assert!(
            n.is_multiple_of(NR) && k.is_multiple_of(2),
            "qgemm needs n % 16 == 0 and even k"
        );
        let scale: Vec<f32> = (0..n)
            .map(|j| {
                let m = (0..k).map(|i| w[i * ldw + j].abs()).fold(0f32, f32::max);
                if m > 0.0 { m / 127.0 } else { 1.0 }
            })
            .collect();
        let q = |i: usize, j: usize| {
            (w[i * ldw + j] / scale[j])
                .round_ties_even()
                .clamp(-127.0, 127.0) as i16
        };
        let mut packed = Vec::with_capacity(k * n);
        for nb in 0..n / NR {
            for p in 0..k / 2 {
                for c in 0..NR {
                    let j = nb * NR + c;
                    packed.push(q(2 * p, j));
                    packed.push(q(2 * p + 1, j));
                }
            }
        }
        Self {
            n,
            k,
            packed,
            scale,
        }
    }
}

/// Quantises `m` rows of width `k` (stride `ldx`) into `q` (m x k) with one scale per row.
pub fn quantize_rows(x: &[f32], ldx: usize, m: usize, k: usize, q: &mut [i16], s: &mut [f32]) {
    assert!(m == 0 || (x.len() >= (m - 1) * ldx + k && q.len() >= m * k && s.len() >= m));
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") && k.is_multiple_of(16) {
        // SAFETY: AVX2 is present; the assert above bounds every access.
        unsafe { quantize_rows_avx2(x, ldx, m, k, q, s) };
        return;
    }
    for r in 0..m {
        let xr = &x[r * ldx..r * ldx + k];
        let mx = xr.iter().fold(0f32, |a, v| a.max(v.abs()));
        let sc = if mx > 0.0 { mx / 127.0 } else { 1.0 };
        s[r] = sc;
        for (o, v) in q[r * k..(r + 1) * k].iter_mut().zip(xr) {
            *o = (v / sc).round_ties_even() as i16;
        }
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn quantize_rows_avx2(
    x: &[f32],
    ldx: usize,
    m: usize,
    k: usize,
    q: &mut [i16],
    s: &mut [f32],
) {
    // SAFETY: callers check AVX2 and the slice bounds
    unsafe {
        let sign = _mm256_set1_ps(-0.0);
        for r in 0..m {
            let xr = x[r * ldx..].as_ptr();
            let mut mx = _mm256_setzero_ps();
            for c in (0..k).step_by(8) {
                mx = _mm256_max_ps(mx, _mm256_andnot_ps(sign, _mm256_loadu_ps(xr.add(c))));
            }
            let mut lanes = [0f32; 8];
            _mm256_storeu_ps(lanes.as_mut_ptr(), mx);
            let mx = lanes.iter().fold(0f32, |a, &b| a.max(b));
            let sc = if mx > 0.0 { mx / 127.0 } else { 1.0 };
            s[r] = sc;
            let inv = _mm256_set1_ps(1.0 / sc);
            let qr = q[r * k..].as_mut_ptr();
            for c in (0..k).step_by(16) {
                // round to nearest even (MXCSR default), then pack two i32 vectors to i16
                let a = _mm256_cvtps_epi32(_mm256_mul_ps(_mm256_loadu_ps(xr.add(c)), inv));
                let b = _mm256_cvtps_epi32(_mm256_mul_ps(_mm256_loadu_ps(xr.add(c + 8)), inv));
                let p = _mm256_permute4x64_epi64::<0b11_01_10_00>(_mm256_packs_epi32(a, b));
                _mm256_storeu_si256(qr.add(c) as *mut __m256i, p);
            }
        }
    }
}

/// out[m x n] (+)= dequant(xq[m x k] * W) + bias, then ReLU if asked. `out` has stride `ldo`.
#[allow(clippy::too_many_arguments)]
pub fn qgemm(
    m: usize,
    xq: &[i16],
    sx: &[f32],
    w: &QLin,
    bias: &[f32],
    out: &mut [f32],
    ldo: usize,
    accumulate: bool,
    relu: bool,
) {
    let (n, k) = (w.n, w.k);
    assert!(xq.len() >= m * k && sx.len() >= m && bias.len() >= n);
    assert!(m == 0 || out.len() >= (m - 1) * ldo + n);
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") {
        // SAFETY: AVX2 is present; the asserts above bound every access.
        unsafe { qgemm_avx2(m, xq, sx, w, bias, out, ldo, accumulate, relu) };
        return;
    }
    for r in 0..m {
        for j in 0..n {
            let (nb, c) = (j / NR, j % NR);
            let mut acc = 0i32;
            for p in 0..k / 2 {
                let b = &w.packed[(nb * (k / 2) + p) * 2 * NR + 2 * c..];
                acc += xq[r * k + 2 * p] as i32 * b[0] as i32
                    + xq[r * k + 2 * p + 1] as i32 * b[1] as i32;
            }
            let v = acc as f32 * sx[r] * w.scale[j] + bias[j];
            let o = &mut out[r * ldo + j];
            let v = if accumulate { *o + v } else { v };
            *o = if relu { v.max(0.0) } else { v };
        }
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
#[allow(clippy::too_many_arguments)]
unsafe fn qgemm_avx2(
    m: usize,
    xq: &[i16],
    sx: &[f32],
    w: &QLin,
    bias: &[f32],
    out: &mut [f32],
    ldo: usize,
    accumulate: bool,
    relu: bool,
) {
    // SAFETY: callers check AVX2 and the slice bounds
    unsafe {
        let n = w.n;
        for nb in 0..n / NR {
            let mut r = 0;
            while r + 4 <= m {
                tile::<4>(r, nb, xq, sx, w, bias, out, ldo, accumulate, relu);
                r += 4;
            }
            match m - r {
                3 => tile::<3>(r, nb, xq, sx, w, bias, out, ldo, accumulate, relu),
                2 => tile::<2>(r, nb, xq, sx, w, bias, out, ldo, accumulate, relu),
                1 => tile::<1>(r, nb, xq, sx, w, bias, out, ldo, accumulate, relu),
                _ => {}
            }
        }
    }
}

/// R rows x 16 columns (block `nb`) starting at row `r`, sums held in 2R registers.
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
#[inline]
#[allow(clippy::too_many_arguments)]
unsafe fn tile<const R: usize>(
    r: usize,
    nb: usize,
    xq: &[i16],
    sx: &[f32],
    w: &QLin,
    bias: &[f32],
    out: &mut [f32],
    ldo: usize,
    accumulate: bool,
    relu: bool,
) {
    // SAFETY: callers check AVX2 and the slice bounds
    unsafe {
        let k = w.k;
        let kp = k / 2;
        let b = w.packed[nb * kp * 2 * NR..].as_ptr();
        let a = xq[r * k..].as_ptr();
        let mut acc = [[_mm256_setzero_si256(); 2]; R];
        for p in 0..kp {
            let b0 = _mm256_loadu_si256(b.add(p * 2 * NR) as *const __m256i);
            let b1 = _mm256_loadu_si256(b.add(p * 2 * NR + NR) as *const __m256i);
            for (i, acc) in acc.iter_mut().enumerate() {
                let av = _mm256_set1_epi32((a.add(i * k + 2 * p) as *const i32).read_unaligned());
                acc[0] = _mm256_add_epi32(acc[0], _mm256_madd_epi16(av, b0));
                acc[1] = _mm256_add_epi32(acc[1], _mm256_madd_epi16(av, b1));
            }
        }
        let col = nb * NR;
        for (i, acc) in acc.iter().enumerate() {
            let s = _mm256_set1_ps(sx[r + i]);
            let o = out[(r + i) * ldo + col..].as_mut_ptr();
            for h in 0..2 {
                let ws = _mm256_loadu_ps(w.scale[col + 8 * h..].as_ptr());
                let bv = _mm256_loadu_ps(bias[col + 8 * h..].as_ptr());
                let mut v = _mm256_fmadd_ps(_mm256_cvtepi32_ps(acc[h]), _mm256_mul_ps(s, ws), bv);
                if accumulate {
                    v = _mm256_add_ps(v, _mm256_loadu_ps(o.add(8 * h)));
                }
                if relu {
                    v = _mm256_max_ps(v, _mm256_setzero_ps());
                }
                _mm256_storeu_ps(o.add(8 * h), v);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qgemm_matches_float_within_quantisation_error() {
        let (m, k, n, ldw) = (7, 40, 32, 48);
        let x: Vec<f32> = (0..m * k)
            .map(|i| ((i * 37 % 101) as f32 - 50.0) / 25.0)
            .collect();
        let w: Vec<f32> = (0..k * ldw)
            .map(|i| ((i * 53 % 97) as f32 - 48.0) / 60.0)
            .collect();
        let bias: Vec<f32> = (0..n).map(|j| j as f32 / 10.0).collect();
        let lin = QLin::new(&w[8..], ldw, k, n);
        let (mut q, mut s) = (vec![0i16; m * k], vec![0f32; m]);
        quantize_rows(&x, k, m, k, &mut q, &mut s);
        let mut got = vec![1f32; m * n];
        qgemm(m, &q, &s, &lin, &bias, &mut got, n, true, false);
        for r in 0..m {
            for j in 0..n {
                // exactly the integer product of the quantised values ...
                let wq = |i: usize| (w[i * ldw + 8 + j] / lin.scale[j]).round_ties_even() as i32;
                let acc: i32 = (0..k).map(|i| q[r * k + i] as i32 * wq(i)).sum();
                let exact = acc as f32 * s[r] * lin.scale[j] + bias[j] + 1.0;
                let g = got[r * n + j];
                assert!(
                    (g - exact).abs() <= 1e-5 * exact.abs().max(1.0),
                    "({r},{j}) {g} vs {exact}"
                );
                // ... and close to the float product (|x| <= 2, |w| <= 0.8, k = 40)
                let float: f32 = (0..k)
                    .map(|i| x[r * k + i] * w[i * ldw + 8 + j])
                    .sum::<f32>()
                    + bias[j]
                    + 1.0;
                assert!((g - float).abs() < 0.15, "({r},{j}) {g} vs float {float}");
            }
        }
    }
}

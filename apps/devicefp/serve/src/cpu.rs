//! CPU engine: the restructured forward pass in fp32, profiles split into chunks across threads.
//!
//! [`Options`] switch the restructuring off piece by piece and add the recall-mode variants
//! studied in the README (int8 GEMMs, fp16 or int8 layer-1 tables); the defaults are the service.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use half::f16;
use rayon::prelude::*;

use crate::math::{self, matmul};
use crate::model::{Block, Model, Tower};
use crate::qgemm::{self, QLin};
use crate::{Dtype, Engine, Mode, Options};

pub struct CpuEngine {
    model: Arc<Model>,
    opts: Options,
    recall: Dtype,
    /// recall mode: int8 weights, and the layer-1 tables when stored below fp32
    q: Vec<QTower>,
    tables: Vec<Option<Tables>>,
    /// Options::profile: thread time per stage, summed over threads (seconds)
    profile: Mutex<HashMap<&'static str, f64>>,
}

/// int8 copies of one tower's linear layers.
struct QTower {
    l1: QBlock,
    l2: QBlock,
    head: QLin,
}

struct QBlock {
    qkv: QLin,
    q: QLin,
    kv: QLin,
    out: QLin,
    w1: QLin,
    w2: QLin,
}

impl QBlock {
    fn new(b: &Block, d: usize, ffn: usize) -> Self {
        Self {
            qkv: QLin::new(&b.in_w, 3 * d, d, 3 * d),
            q: QLin::new(&b.in_w, 3 * d, d, d),
            kv: QLin::new(&b.in_w[d..], 3 * d, d, 2 * d),
            out: QLin::new(&b.out_w, d, d, d),
            w1: QLin::new(&b.w1, ffn, d, ffn),
            w2: QLin::new(&b.w2, d, ffn, d),
        }
    }
}

/// Layer-1 tables (`tok`, `qkv1`) stored below fp32; rows are widened to fp32 when gathered.
enum Tables {
    F16 {
        tok: Vec<f16>,
        qkv1: Vec<f16>,
    },
    /// one scale per d-wide chunk of a row
    I8 {
        tok: Vec<i8>,
        tok_s: Vec<f32>,
        qkv1: Vec<i8>,
        qkv1_s: Vec<f32>,
    },
}

fn quantize_chunks(x: &[f32], d: usize) -> (Vec<i8>, Vec<f32>) {
    let mut q = vec![0i8; x.len()];
    let mut s = vec![0f32; x.len() / d];
    for ((xc, qc), sc) in x.chunks_exact(d).zip(q.chunks_exact_mut(d)).zip(&mut s) {
        let m = xc.iter().fold(0f32, |a, v| a.max(v.abs()));
        *sc = if m > 0.0 { m / 127.0 } else { 1.0 };
        for (o, v) in qc.iter_mut().zip(xc) {
            *o = (v / *sc).round_ties_even() as i8;
        }
    }
    (q, s)
}

impl Tables {
    fn new(t: &Tower, dt: Dtype) -> Option<Self> {
        match dt {
            Dtype::F32 => None,
            Dtype::F16 => Some(Self::F16 {
                tok: t.tok.iter().map(|&v| f16::from_f32(v)).collect(),
                qkv1: t.qkv1.iter().map(|&v| f16::from_f32(v)).collect(),
            }),
            Dtype::I8 => {
                let (tok, tok_s) = quantize_chunks(&t.tok, t.d);
                let (qkv1, qkv1_s) = quantize_chunks(&t.qkv1, t.d);
                Some(Self::I8 {
                    tok,
                    tok_s,
                    qkv1,
                    qkv1_s,
                })
            }
        }
    }

    /// row v of tok (width d) or qkv1 (width 3d)
    fn row(&self, qkv: bool, v: usize, d: usize, out: &mut [f32]) {
        let w = if qkv { 3 * d } else { d };
        match self {
            Self::F16 { tok, qkv1 } => {
                let src = if qkv { qkv1 } else { tok };
                for (o, h) in out.iter_mut().zip(&src[v * w..(v + 1) * w]) {
                    *o = h.to_f32();
                }
            }
            Self::I8 {
                tok,
                tok_s,
                qkv1,
                qkv1_s,
            } => {
                let (src, s) = if qkv { (qkv1, qkv1_s) } else { (tok, tok_s) };
                for (c, o) in out.iter_mut().enumerate() {
                    let e = v * w + c;
                    *o = src[e] as f32 * s[e / d];
                }
            }
        }
    }
}

impl CpuEngine {
    pub fn new(model: Arc<Model>) -> Self {
        Self::with_options(model, Options::default())
    }

    pub fn with_options(model: Arc<Model>, opts: Options) -> Self {
        let recall = opts.recall.unwrap_or(Dtype::F32);
        assert!(
            recall != Dtype::F16,
            "the CPU engine has no fp16 compute path"
        );
        let q = if recall == Dtype::I8 {
            model
                .towers
                .iter()
                .map(|t| QTower {
                    l1: QBlock::new(&t.l1, t.d, t.ffn),
                    l2: QBlock::new(&t.l2, t.d, t.ffn),
                    head: QLin::new(&t.head_w, t.out, t.d, t.out),
                })
                .collect()
        } else {
            Vec::new()
        };
        let tdt = opts.recall_tables.unwrap_or(Dtype::F32);
        let tables = model.towers.iter().map(|t| Tables::new(t, tdt)).collect();
        Self {
            model,
            opts,
            recall,
            q,
            tables,
            profile: Mutex::default(),
        }
    }
}

impl Engine for CpuEngine {
    fn name(&self) -> String {
        format!("cpu ({} threads)", rayon::current_num_threads())
    }

    fn dim(&self) -> usize {
        self.model.dim
    }

    fn n_fields(&self) -> usize {
        self.model.n_fields
    }

    fn embed(&self, codes: &[i32], n: usize, mode: Mode, out: &mut [f32]) -> anyhow::Result<()> {
        // By default recall mode runs the fp32 kernels too: no reduced-precision path pays off on
        // CPUs without bf16/int8 dot-product units (see the README for the measurements).
        let (m, nf, dim) = (&*self.model, self.model.n_fields, self.model.dim);
        anyhow::ensure!(
            codes.len() == n * nf && out.len() == n * dim,
            "embed: buffer sizes do not match {n} profiles"
        );
        let recall = mode == Mode::Recall;
        let chunk = self.opts.chunk;
        out.par_chunks_mut(chunk * dim)
            .zip(codes.par_chunks(chunk * nf))
            .for_each(|(o, c)| {
                let rows = c.len() / nf;
                if self.opts.profile {
                    // time between tasks is the scheduler's, not a stage's
                    LAPS.with_borrow_mut(|l| l.last = Instant::now());
                }
                SCRATCH.with_borrow_mut(|s| {
                    for (i, t) in m.towers.iter().enumerate() {
                        let q = (recall && self.recall == Dtype::I8).then(|| &self.q[i]);
                        let tab = if recall {
                            self.tables[i].as_ref()
                        } else {
                            None
                        };
                        let f = Fwd {
                            m,
                            t,
                            q,
                            tab,
                            opts: &self.opts,
                        };
                        f.tower(c, rows, o, s);
                        f.lap("other");
                    }
                });
                if self.opts.profile {
                    let laps = LAPS.with_borrow_mut(|l| std::mem::take(&mut l.acc));
                    let mut p = self.profile.lock().unwrap();
                    for (k, v) in laps {
                        *p.entry(k).or_default() += v;
                    }
                }
            });
        Ok(())
    }

    fn profile(&self) -> Vec<(String, f64)> {
        let mut p = self.profile.lock().unwrap();
        let mut v: Vec<_> = p.drain().map(|(k, s)| (k.to_string(), s)).collect();
        v.sort_by(|a, b| b.1.total_cmp(&a.1));
        v
    }
}

/// Per-thread stage timer for Options::profile: each lap is charged to the stage just finished.
struct Laps {
    last: Instant,
    acc: HashMap<&'static str, f64>,
}

thread_local! {
    // reused across calls: allocating and zeroing per task costs more than the maths
    static SCRATCH: std::cell::RefCell<Scratch> = std::cell::RefCell::new(Scratch::default());
    static LAPS: std::cell::RefCell<Laps> = std::cell::RefCell::new(Laps {
        last: Instant::now(),
        acc: HashMap::new(),
    });
}

#[derive(Default)]
struct Scratch {
    x: Vec<f32>,
    qkv: Vec<f32>,
    att: Vec<f32>,
    h: Vec<f32>,
    f: Vec<f32>,
    s: Vec<f32>,
    q: Vec<f32>,
    c: Vec<f32>,
    y: Vec<f32>,
    xq: Vec<i16>,
    sx: Vec<f32>,
}

/// A scratch slice of length n; contents are stale, every user overwrites before reading.
fn sized<T: Copy + Default>(v: &mut Vec<T>, n: usize) -> &mut [T] {
    if v.len() < n {
        v.resize(n, T::default());
    }
    &mut v[..n]
}

/// A linear layer: fp32 weights (k x n column slice, leading dimension `ldw`), bias, and the
/// int8 copy when the call runs int8 GEMMs.
struct Lin<'a> {
    w: &'a [f32],
    ldw: usize,
    b: &'a [f32],
    q: Option<&'a QLin>,
}

/// One tower's forward pass under the given variant.
struct Fwd<'a> {
    m: &'a Model,
    t: &'a Tower,
    q: Option<&'a QTower>,
    tab: Option<&'a Tables>,
    opts: &'a Options,
}

impl Fwd<'_> {
    fn lap(&self, stage: &'static str) {
        if self.opts.profile {
            LAPS.with_borrow_mut(|l| {
                let now = Instant::now();
                *l.acc.entry(stage).or_default() += (now - l.last).as_secs_f64();
                l.last = now;
            });
        }
    }

    /// out[rows x n] (+)= x[rows x k] W + b, ReLU if asked
    #[allow(clippy::too_many_arguments)]
    fn linear(
        &self,
        s_xq: &mut Vec<i16>,
        s_sx: &mut Vec<f32>,
        rows: usize,
        k: usize,
        x: &[f32],
        ldx: usize,
        lin: Lin,
        out: &mut [f32],
        ldo: usize,
        accumulate: bool,
        relu: bool,
    ) {
        let n = lin.b.len();
        match lin.q {
            None => {
                matmul(rows, n, k, x, ldx, lin.w, lin.ldw, out, ldo, accumulate, 1);
                self.lap("GEMM");
                math::add_bias(out, ldo, lin.b, relu);
                self.lap("bias + activation");
            }
            Some(q) => {
                let xq = sized(s_xq, rows * k);
                let sx = sized(s_sx, rows);
                qgemm::quantize_rows(x, ldx, rows, k, xq, sx);
                self.lap("int8 quantise");
                qgemm::qgemm(rows, xq, sx, q, lin.b, out, ldo, accumulate, relu);
                self.lap("GEMM");
            }
        }
    }

    fn lins(&self, layer: usize) -> (&Block, Option<&QBlock>) {
        let (b, q) = if layer == 1 {
            (&self.t.l1, self.q.map(|q| &q.l1))
        } else {
            (&self.t.l2, self.q.map(|q| &q.l2))
        };
        (b, q)
    }

    /// One tower for `b` profiles; writes the tower's scaled unit vectors into its columns of `out`.
    fn tower(&self, codes: &[i32], b: usize, out: &mut [f32], s: &mut Scratch) {
        let (m, t) = (self.m, self.t);
        let (d, l, ffn, eps) = (t.d, t.l, t.ffn, m.eps);
        let bl = b * l;
        let nf = m.n_fields;
        let Scratch {
            x,
            qkv,
            att,
            h,
            f,
            s: sc,
            q,
            c,
            y,
            xq,
            sx,
        } = s;

        // token embeddings and (with tables) their precomputed layer-1 Q/K/V
        let x = sized(x, bl * d);
        let qkv = sized(qkv, bl * 3 * d);
        for p in 0..b {
            let r0 = p * l;
            x[r0 * d..(r0 + 1) * d].copy_from_slice(&t.cls_tok);
            if self.opts.tables {
                qkv[r0 * 3 * d..(r0 + 1) * 3 * d].copy_from_slice(&t.cls_qkv1);
            }
            for (j, (&fi, &off)) in t.field_idx.iter().zip(&t.offsets).enumerate() {
                let v = (codes[p * nf + fi] + off) as usize;
                debug_assert!(v < t.vocab);
                let r = r0 + 1 + j;
                let (xr, qr) = (
                    &mut x[r * d..(r + 1) * d],
                    &mut qkv[r * 3 * d..(r + 1) * 3 * d],
                );
                match self.tab {
                    None => {
                        xr.copy_from_slice(&t.tok[v * d..(v + 1) * d]);
                        if self.opts.tables {
                            qr.copy_from_slice(&t.qkv1[v * 3 * d..(v + 1) * 3 * d]);
                        }
                    }
                    Some(tab) => {
                        tab.row(false, v, d, xr);
                        if self.opts.tables {
                            tab.row(true, v, d, qr);
                        }
                    }
                }
            }
        }
        self.lap("gather");
        let h = sized(h, bl * d);
        let (k1, q1) = self.lins(1);
        if !self.opts.tables {
            math::layer_norm(x, h, &k1.n1_w, &k1.n1_b, eps);
            self.lap("layernorm");
            let lin = Lin {
                w: &k1.in_w,
                ldw: 3 * d,
                b: &k1.in_b,
                q: q1.map(|q| &q.qkv),
            };
            self.linear(xq, sx, bl, d, h, d, lin, qkv, 3 * d, false, false);
        }

        // layer 1, every token
        let att = sized(att, bl * d);
        math::attention_full(qkv, b, l, d, t.heads, att, sized(sc, l * l));
        self.lap("attention");
        let f = sized(f, bl * ffn);
        self.rest_of_layer(xq, sx, k1, q1, bl, att, x, h, f);

        let (k2, q2) = self.lins(2);
        let c = sized(c, b * d);
        if self.opts.cls_only {
            // layer 2: K/V for every token, the rest for CLS rows only
            math::layer_norm(x, h, &k2.n1_w, &k2.n1_b, eps);
            self.lap("layernorm");
            let kv = &mut qkv[..bl * 2 * d];
            let lin = Lin {
                w: &k2.in_w[d..],
                ldw: 3 * d,
                b: &k2.in_b[d..],
                q: q2.map(|q| &q.kv),
            };
            self.linear(xq, sx, bl, d, h, d, lin, kv, 2 * d, false, false);
            let qc = sized(q, b * d);
            let lin = Lin {
                w: &k2.in_w,
                ldw: 3 * d,
                b: &k2.in_b[..d],
                q: q2.map(|q| &q.q),
            };
            self.linear(xq, sx, b, d, h, l * d, lin, qc, d, false, false);
            let a = &mut att[..b * d];
            math::attention_one(qc, kv, b, l, d, t.heads, a, sized(sc, l));
            self.lap("attention");
            for p in 0..b {
                c[p * d..(p + 1) * d].copy_from_slice(&x[p * l * d..p * l * d + d]);
            }
            let (hc, fc) = (&mut h[..b * d], &mut f[..b * ffn]);
            self.rest_of_layer(xq, sx, k2, q2, b, a, c, hc, fc);
        } else {
            // the full second layer, then the CLS rows
            math::layer_norm(x, h, &k2.n1_w, &k2.n1_b, eps);
            self.lap("layernorm");
            let lin = Lin {
                w: &k2.in_w,
                ldw: 3 * d,
                b: &k2.in_b,
                q: q2.map(|q| &q.qkv),
            };
            self.linear(xq, sx, bl, d, h, d, lin, qkv, 3 * d, false, false);
            math::attention_full(qkv, b, l, d, t.heads, att, sized(sc, l * l));
            self.lap("attention");
            self.rest_of_layer(xq, sx, k2, q2, bl, att, x, h, f);
            for p in 0..b {
                c[p * d..(p + 1) * d].copy_from_slice(&x[p * l * d..p * l * d + d]);
            }
        }

        // head: LayerNorm, Linear, unit length, sqrt(w) scale
        let hc = &mut h[..b * d];
        self.lap("other");
        math::layer_norm(c, hc, &t.head_ln_w, &t.head_ln_b, eps);
        self.lap("layernorm");
        let y = sized(y, b * t.out);
        let lin = Lin {
            w: &t.head_w,
            ldw: t.out,
            b: &t.head_b,
            q: self.q.map(|q| &q.head),
        };
        self.linear(xq, sx, b, d, hc, d, lin, y, t.out, false, false);
        math::normalize_rows(y, t.out, t.scale);
        for p in 0..b {
            out[p * m.dim + t.col..p * m.dim + t.col + t.out]
                .copy_from_slice(&y[p * t.out..(p + 1) * t.out]);
        }
    }

    /// x += out_proj(att); x += FFN(LN2(x)), over `rows` rows of width d
    #[allow(clippy::too_many_arguments)]
    fn rest_of_layer(
        &self,
        xq: &mut Vec<i16>,
        sx: &mut Vec<f32>,
        k: &Block,
        q: Option<&QBlock>,
        rows: usize,
        att: &[f32],
        x: &mut [f32],
        h: &mut [f32],
        f: &mut [f32],
    ) {
        let (d, ffn) = (self.t.d, self.t.ffn);
        let lin = Lin {
            w: &k.out_w,
            ldw: d,
            b: &k.out_b,
            q: q.map(|q| &q.out),
        };
        self.linear(xq, sx, rows, d, att, d, lin, x, d, true, false);
        math::layer_norm(x, h, &k.n2_w, &k.n2_b, self.m.eps);
        self.lap("layernorm");
        let lin = Lin {
            w: &k.w1,
            ldw: ffn,
            b: &k.b1,
            q: q.map(|q| &q.w1),
        };
        self.linear(xq, sx, rows, d, h, d, lin, f, ffn, false, true);
        let lin = Lin {
            w: &k.w2,
            ldw: d,
            b: &k.b2,
            q: q.map(|q| &q.w2),
        };
        self.linear(xq, sx, rows, ffn, f, ffn, lin, x, d, true, false);
    }
}

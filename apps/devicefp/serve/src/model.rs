//! The v3 towers in inference form, shared by the CPU and GPU engines.
//!
//! A tower is FieldEncoder from devicefp/v2.py: token = value embedding + field embedding, a CLS
//! token in front, two pre-norm transformer layers (ReLU FFN of width 4d), LayerNorm + Linear on
//! the CLS output, unit-normalised. Two exact rewrites cut the work roughly in half:
//!
//! * layer 1 sees each token in isolation until attention, so `tok` and its Q/K/V (`qkv1`) are
//!   precomputed for every vocabulary entry and gathered at inference;
//! * only the CLS output is used, so layer 2 computes K/V for every token but the query,
//!   attention output, residual and FFN for the CLS token alone.
//!
//! Weight matrices are stored transposed (in x out, row-major) for `x @ W^T` as a plain GEMM.

use anyhow::{Result, bail};
use rayon::prelude::*;

use crate::bundle::{Bundle, Tensor};
use crate::math;

pub struct Block {
    pub n1_w: Vec<f32>,
    pub n1_b: Vec<f32>,
    /// d x 3d: columns [q | k | v]
    pub in_w: Vec<f32>,
    pub in_b: Vec<f32>,
    pub out_w: Vec<f32>,
    pub out_b: Vec<f32>,
    pub n2_w: Vec<f32>,
    pub n2_b: Vec<f32>,
    pub w1: Vec<f32>,
    pub b1: Vec<f32>,
    pub w2: Vec<f32>,
    pub b2: Vec<f32>,
}

pub struct Tower {
    pub name: String,
    pub d: usize,
    pub heads: usize,
    pub out: usize,
    /// sequence length: fields + CLS
    pub l: usize,
    pub ffn: usize,
    /// sqrt(factor weight): the dot product of two combined vectors is the v3 score
    pub scale: f32,
    /// first column of this tower in the combined vector
    pub col: usize,
    /// for each tower field, its index among the encoder fields and its token-id offset
    pub field_idx: Vec<usize>,
    pub offsets: Vec<i32>,
    pub vocab: usize,
    /// vocab x d and vocab x 3d
    pub tok: Vec<f32>,
    pub qkv1: Vec<f32>,
    pub cls_tok: Vec<f32>,
    pub cls_qkv1: Vec<f32>,
    pub l1: Block,
    pub l2: Block,
    pub head_ln_w: Vec<f32>,
    pub head_ln_b: Vec<f32>,
    pub head_w: Vec<f32>,
    pub head_b: Vec<f32>,
}

pub struct Model {
    pub name: String,
    pub towers: Vec<Tower>,
    pub dim: usize,
    pub n_fields: usize,
    pub eps: f32,
}

fn transpose(t: &Tensor) -> Vec<f32> {
    let (r, c) = (t.shape[0], t.shape[1]);
    let mut out = vec![0.0; r * c];
    for i in 0..r {
        for j in 0..c {
            out[j * r + i] = t.data[i * c + j];
        }
    }
    out
}

impl Model {
    pub fn from_bundle(b: &Bundle) -> Result<Self> {
        let spec = &b.spec;
        let eps = spec.layer_norm_eps;
        let mut towers = Vec::new();
        let mut col = 0;
        for ts in &spec.towers {
            if ts.layers != 2 {
                bail!("tower {}: only 2-layer towers are supported", ts.name);
            }
            let p = |s: &str| format!("towers.{}.{s}", ts.name);
            let get = |s: &str| b.tensor(&p(s));
            let block = |i: usize| -> Result<Block> {
                let l = |s: &str| get(&format!("encoder.layers.{i}.{s}"));
                Ok(Block {
                    n1_w: l("norm1.weight")?.data.clone(),
                    n1_b: l("norm1.bias")?.data.clone(),
                    in_w: transpose(l("self_attn.in_proj_weight")?),
                    in_b: l("self_attn.in_proj_bias")?.data.clone(),
                    out_w: transpose(l("self_attn.out_proj.weight")?),
                    out_b: l("self_attn.out_proj.bias")?.data.clone(),
                    n2_w: l("norm2.weight")?.data.clone(),
                    n2_b: l("norm2.bias")?.data.clone(),
                    w1: transpose(l("linear1.weight")?),
                    b1: l("linear1.bias")?.data.clone(),
                    w2: transpose(l("linear2.weight")?),
                    b2: l("linear2.bias")?.data.clone(),
                })
            };
            let d = ts.d;
            let values = get("values.weight")?;
            let field = get("field")?;
            if values.shape != [ts.vocab, d] || field.shape != [ts.fields.len(), d] {
                bail!(
                    "tower {}: embedding shapes do not match the encoder spec",
                    ts.name
                );
            }
            let mut field_idx = Vec::new();
            let mut offsets = Vec::new();
            let mut off = 0;
            for f in &ts.fields {
                let Some(j) = spec.fields.iter().position(|x| &x.name == f) else {
                    bail!("tower {}: unknown field {f}", ts.name)
                };
                field_idx.push(j);
                offsets.push(off);
                off += spec.fields[j].size;
            }
            if off as usize != ts.vocab {
                bail!(
                    "tower {}: field sizes sum to {off}, vocab is {}",
                    ts.name,
                    ts.vocab
                );
            }
            let l1 = block(0)?;
            let l2 = block(1)?;

            // tok[v] = value[v] + field[f(v)], then qkv1[v] = LN1(tok[v]) @ W_in^T + b_in
            let mut tok = values.data.clone();
            for (fi, &o) in offsets.iter().enumerate() {
                let end = offsets.get(fi + 1).copied().unwrap_or(off);
                for v in o as usize..end as usize {
                    for c in 0..d {
                        tok[v * d + c] += field.data[fi * d + c];
                    }
                }
            }
            let qkv1 = table_qkv(&tok, ts.vocab, d, &l1, eps);
            let cls_tok = get("cls")?.data.clone();
            let cls_qkv1 = table_qkv(&cls_tok, 1, d, &l1, eps);

            towers.push(Tower {
                name: ts.name.clone(),
                d,
                heads: ts.heads,
                out: ts.out,
                l: ts.fields.len() + 1,
                ffn: l1.b1.len(),
                scale: ts.weight.sqrt(),
                col,
                field_idx,
                offsets,
                vocab: ts.vocab,
                tok,
                qkv1,
                cls_tok,
                cls_qkv1,
                l1,
                l2,
                head_ln_w: get("head.0.weight")?.data.clone(),
                head_ln_b: get("head.0.bias")?.data.clone(),
                head_w: transpose(get("head.1.weight")?),
                head_b: get("head.1.bias")?.data.clone(),
            });
            col += ts.out;
        }
        if col != spec.dim {
            bail!("tower outputs sum to {col}, spec dim is {}", spec.dim);
        }
        Ok(Self {
            name: spec.model.clone(),
            towers,
            dim: col,
            n_fields: spec.fields.len(),
            eps,
        })
    }
}

fn table_qkv(tok: &[f32], rows: usize, d: usize, l1: &Block, eps: f32) -> Vec<f32> {
    let mut normed = vec![0.0; rows * d];
    normed
        .par_chunks_mut(4096 * d)
        .zip(tok.par_chunks(4096 * d))
        .for_each(|(o, x)| math::layer_norm(x, o, &l1.n1_w, &l1.n1_b, eps));
    let mut out = vec![0.0; rows * 3 * d];
    math::matmul(
        rows,
        3 * d,
        d,
        &normed,
        d,
        &l1.in_w,
        3 * d,
        &mut out,
        3 * d,
        false,
        rayon::current_num_threads(),
    );
    math::add_bias(&mut out, 3 * d, &l1.in_b, false);
    out
}

//! The restructured CPU forward pass against a direct transformer implementation on a random model.

use std::collections::HashMap;
use std::sync::Arc;

use devicefp_serve::bundle::{Bundle, EncoderSpec, Tensor};
use devicefp_serve::cpu::CpuEngine;
use devicefp_serve::model::Model;
use devicefp_serve::{Engine, Mode};

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> f32 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        ((self.0 >> 40) as f32 / (1u64 << 24) as f32 - 0.5) * 0.6
    }
    fn vec(&mut self, n: usize) -> Vec<f32> {
        (0..n).map(|_| self.next()).collect()
    }
}

const D: usize = 16;
const HEADS: usize = 2;
const OUT: usize = 8;
const SIZES: [i32; 3] = [5, 4, 6];

fn bundle() -> Bundle {
    let fields: Vec<_> = SIZES.iter().enumerate().map(|(i, &s)| serde_json::json!({"name": format!("f{i}"), "size": s, "raw": "int", "kind": "num", "edges": []})).collect();
    let vocab: i32 = SIZES.iter().sum();
    let spec: EncoderSpec = serde_json::from_value(serde_json::json!({
        "model": "test", "placeholders": [], "layer_norm_eps": 1e-5, "dim": OUT, "fields": fields,
        "towers": [{"name": "t", "fields": ["f0", "f1", "f2"], "d": D, "out": OUT, "heads": HEADS, "layers": 2, "vocab": vocab, "weight": 0.64}]
    }))
    .unwrap();
    let mut r = Rng(0x9e3779b97f4a7c15);
    let mut t = HashMap::new();
    let mut put = |name: &str, shape: Vec<usize>, r: &mut Rng| {
        let n = shape.iter().product();
        t.insert(
            format!("towers.t.{name}"),
            Tensor {
                shape,
                data: r.vec(n),
            },
        );
    };
    put("values.weight", vec![vocab as usize, D], &mut r);
    put("field", vec![3, D], &mut r);
    put("cls", vec![1, 1, D], &mut r);
    for i in 0..2 {
        let l = |s: &str| format!("encoder.layers.{i}.{s}");
        put(&l("self_attn.in_proj_weight"), vec![3 * D, D], &mut r);
        put(&l("self_attn.in_proj_bias"), vec![3 * D], &mut r);
        put(&l("self_attn.out_proj.weight"), vec![D, D], &mut r);
        put(&l("self_attn.out_proj.bias"), vec![D], &mut r);
        put(&l("linear1.weight"), vec![4 * D, D], &mut r);
        put(&l("linear1.bias"), vec![4 * D], &mut r);
        put(&l("linear2.weight"), vec![D, 4 * D], &mut r);
        put(&l("linear2.bias"), vec![D], &mut r);
        for nm in ["norm1", "norm2"] {
            put(&l(&format!("{nm}.weight")), vec![D], &mut r);
            put(&l(&format!("{nm}.bias")), vec![D], &mut r);
        }
    }
    put("head.0.weight", vec![D], &mut r);
    put("head.0.bias", vec![D], &mut r);
    put("head.1.weight", vec![OUT, D], &mut r);
    put("head.1.bias", vec![OUT], &mut r);
    Bundle { spec, tensors: t }
}

// ---- direct reference: nn.TransformerEncoderLayer(norm_first=True, relu), every token, f64

fn get<'a>(b: &'a Bundle, n: &str) -> &'a [f32] {
    &b.tensors[&format!("towers.t.{n}")].data
}

fn linear(x: &[f64], w: &[f32], bias: &[f32], out: usize) -> Vec<f64> {
    let k = x.len();
    (0..out)
        .map(|o| bias[o] as f64 + (0..k).map(|i| x[i] * w[o * k + i] as f64).sum::<f64>())
        .collect()
}

fn ln(x: &[f64], w: &[f32], b: &[f32]) -> Vec<f64> {
    let n = x.len() as f64;
    let m = x.iter().sum::<f64>() / n;
    let v = x.iter().map(|a| (a - m).powi(2)).sum::<f64>() / n;
    x.iter()
        .enumerate()
        .map(|(i, a)| (a - m) / (v + 1e-5).sqrt() * w[i] as f64 + b[i] as f64)
        .collect()
}

fn reference(b: &Bundle, codes: &[i32]) -> Vec<f64> {
    let offs = [0, SIZES[0], SIZES[0] + SIZES[1]];
    let mut x: Vec<Vec<f64>> = vec![get(b, "cls").iter().map(|v| *v as f64).collect()];
    for (j, &c) in codes.iter().enumerate() {
        let v = (c + offs[j]) as usize;
        x.push(
            (0..D)
                .map(|k| (get(b, "values.weight")[v * D + k] + get(b, "field")[j * D + k]) as f64)
                .collect(),
        );
    }
    let dh = D / HEADS;
    for layer in 0..2 {
        let p = |s: &str| get(b, &format!("encoder.layers.{layer}.{s}"));
        let h: Vec<Vec<f64>> = x
            .iter()
            .map(|t| ln(t, p("norm1.weight"), p("norm1.bias")))
            .collect();
        let qkv: Vec<Vec<f64>> = h
            .iter()
            .map(|t| {
                linear(
                    t,
                    p("self_attn.in_proj_weight"),
                    p("self_attn.in_proj_bias"),
                    3 * D,
                )
            })
            .collect();
        let mut att = vec![vec![0.0; D]; x.len()];
        for hd in 0..HEADS {
            for i in 0..x.len() {
                let s: Vec<f64> = (0..x.len())
                    .map(|j| {
                        (0..dh)
                            .map(|c| qkv[i][hd * dh + c] * qkv[j][D + hd * dh + c])
                            .sum::<f64>()
                            / (dh as f64).sqrt()
                    })
                    .collect();
                let m = s.iter().cloned().fold(f64::MIN, f64::max);
                let e: Vec<f64> = s.iter().map(|v| (v - m).exp()).collect();
                let z: f64 = e.iter().sum();
                for c in 0..dh {
                    att[i][hd * dh + c] = (0..x.len())
                        .map(|j| e[j] / z * qkv[j][2 * D + hd * dh + c])
                        .sum();
                }
            }
        }
        for i in 0..x.len() {
            let o = linear(
                &att[i],
                p("self_attn.out_proj.weight"),
                p("self_attn.out_proj.bias"),
                D,
            );
            for k in 0..D {
                x[i][k] += o[k];
            }
            let f: Vec<f64> = linear(
                &ln(&x[i], p("norm2.weight"), p("norm2.bias")),
                p("linear1.weight"),
                p("linear1.bias"),
                4 * D,
            )
            .into_iter()
            .map(|v| v.max(0.0))
            .collect();
            let f = linear(&f, p("linear2.weight"), p("linear2.bias"), D);
            for k in 0..D {
                x[i][k] += f[k];
            }
        }
    }
    let y = linear(
        &ln(&x[0], get(b, "head.0.weight"), get(b, "head.0.bias")),
        get(b, "head.1.weight"),
        get(b, "head.1.bias"),
        OUT,
    );
    let n = y.iter().map(|v| v * v).sum::<f64>().sqrt();
    y.iter().map(|v| v / n * 0.8).collect()
}

#[test]
fn restructured_forward_matches_direct_transformer() {
    let b = bundle();
    let model = Arc::new(Model::from_bundle(&b).unwrap());
    let engine = CpuEngine::new(model);
    let profiles: Vec<[i32; 3]> = (0..7)
        .map(|i| [i % 5, (i * 3) % 4, (i * 5 + 1) % 6])
        .collect();
    let codes: Vec<i32> = profiles.iter().flatten().copied().collect();
    let mut out = vec![0f32; profiles.len() * OUT];
    engine
        .embed(&codes, profiles.len(), Mode::Precision, &mut out)
        .unwrap();
    for (p, row) in profiles.iter().zip(out.chunks(OUT)) {
        let want = reference(&b, p);
        for (g, w) in row.iter().zip(&want) {
            assert!((*g as f64 - w).abs() < 2e-6, "got {g}, want {w}");
        }
    }
}

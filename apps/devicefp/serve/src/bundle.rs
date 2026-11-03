//! Loading an exported v3 bundle: `encoder.json` and `model.safetensors` (see devicefp/export.py).

use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result, bail};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct EncoderSpec {
    pub model: String,
    pub placeholders: Vec<String>,
    pub layer_norm_eps: f32,
    pub dim: usize,
    pub fields: Vec<FieldSpec>,
    pub towers: Vec<TowerSpec>,
}

#[derive(Debug, Deserialize)]
pub struct FieldSpec {
    pub name: String,
    pub size: i32,
    /// training dtype of the raw column: string, bool, int or float
    pub raw: String,
    pub kind: FieldKind,
    #[serde(default)]
    pub vocab: HashMap<String, i32>,
    #[serde(default)]
    pub edges: Vec<f64>,
    pub derived: Option<Derived>,
}

#[derive(Debug, Deserialize, PartialEq, Eq, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum FieldKind {
    Cat,
    Num,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Derived {
    GeoCell {
        lat: String,
        lon: String,
        decimals: i32,
        sep: String,
    },
    Regex {
        from: String,
        pattern: String,
    },
}

#[derive(Debug, Deserialize)]
pub struct TowerSpec {
    pub name: String,
    pub fields: Vec<String>,
    pub d: usize,
    pub out: usize,
    pub heads: usize,
    pub layers: usize,
    pub vocab: usize,
    pub weight: f32,
}

pub struct Tensor {
    pub shape: Vec<usize>,
    pub data: Vec<f32>,
}

pub struct Bundle {
    pub spec: EncoderSpec,
    pub tensors: HashMap<String, Tensor>,
}

impl Bundle {
    pub fn load(dir: &Path) -> Result<Self> {
        let spec: EncoderSpec = serde_json::from_slice(
            &std::fs::read(dir.join("encoder.json"))
                .with_context(|| format!("reading {}/encoder.json", dir.display()))?,
        )?;
        let tensors = read_safetensors(&dir.join("model.safetensors"))?;
        Ok(Self { spec, tensors })
    }

    pub fn tensor(&self, name: &str) -> Result<&Tensor> {
        self.tensors
            .get(name)
            .with_context(|| format!("tensor {name} missing from the bundle"))
    }
}

#[derive(Deserialize)]
struct TensorHeader {
    dtype: String,
    shape: Vec<usize>,
    data_offsets: [usize; 2],
}

/// F32 safetensors only, which is what the exporter writes.
pub fn read_safetensors(path: &Path) -> Result<HashMap<String, Tensor>> {
    let bytes = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    let n = u64::from_le_bytes(bytes[..8].try_into()?) as usize;
    let header: HashMap<String, serde_json::Value> = serde_json::from_slice(&bytes[8..8 + n])?;
    let body = &bytes[8 + n..];
    let mut out = HashMap::new();
    for (name, v) in header {
        if name == "__metadata__" {
            continue;
        }
        let h: TensorHeader = serde_json::from_value(v)?;
        if h.dtype != "F32" {
            bail!("tensor {name}: dtype {} is not F32", h.dtype);
        }
        let raw = &body[h.data_offsets[0]..h.data_offsets[1]];
        let data = raw
            .as_chunks::<4>()
            .0
            .iter()
            .map(|c| f32::from_le_bytes(*c))
            .collect();
        out.insert(
            name,
            Tensor {
                shape: h.shape,
                data,
            },
        );
    }
    Ok(out)
}

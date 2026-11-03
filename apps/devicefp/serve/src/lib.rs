//! Native inference for the devicefp v3 factorised device embedding.
//!
//! A raw JSON profile is encoded into per-field codes ([`encoder`]), then embedded by an
//! [`Engine`] on the CPU ([`cpu`]) or an NVIDIA GPU (`gpu`, feature `cuda`). The output is the
//! 160-d combined vector concat_k sqrt(w_k) z_k: the dot product of two vectors is the v3 score.

pub mod bundle;
pub mod cpu;
pub mod encoder;
#[cfg(feature = "cuda")]
pub mod gpu;
pub mod math;
pub mod model;
pub mod qgemm;
pub mod service;

use serde::{Deserialize, Serialize};

/// `precision`: fp32 throughout, within float noise of the PyTorch model.
/// `recall`: reduced precision where the hardware makes it faster (fp16 on GPU).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Precision,
    Recall,
}

/// Number format of a computation or a stored table.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Dtype {
    F32,
    F16,
    /// symmetric int8 with a float scale per row (per d-wide chunk for tables)
    I8,
}

/// Engine variants for the optimisation study (`devicefp-check`). The service runs the defaults.
#[derive(Debug, Clone)]
pub struct Options {
    /// gather layer-1 Q/K/V from per-value tables (off: LayerNorm + Q/K/V projection per token)
    pub tables: bool,
    /// layer 2 for the CLS row only (off: the full layer for every token)
    pub cls_only: bool,
    /// GPU: fused attention kernels (off: cuBLAS batched GEMMs and a softmax kernel)
    pub fused_attn: bool,
    /// GPU: replay captured CUDA graphs (off: launch every kernel on each call)
    pub graphs: bool,
    /// GPU: bias and ReLU of fp16 GEMMs in the GEMM epilogue (cuBLASLt) instead of a separate
    /// kernel (recall mode +33% on an RTX 2070)
    pub fused_bias: bool,
    /// GPU: the same for fp32 GEMMs (slower than SGEMM + bias kernel on an RTX 2070)
    pub fused_bias_fp32: bool,
    /// CPU: profiles per thread task
    pub chunk: usize,
    /// what recall mode computes in; None: the engine's default (GPU fp16, CPU fp32).
    /// I8 means int8 GEMMs (per-row activation and per-column weight scales), the rest as for F16
    /// on the GPU and F32 on the CPU.
    pub recall: Option<Dtype>,
    /// storage of the layer-1 tables in recall mode; None: the recall activation type
    pub recall_tables: Option<Dtype>,
    /// time each stage of the forward pass (read with [`Engine::profile`]); GPU runs without graphs
    pub profile: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            tables: true,
            cls_only: true,
            fused_attn: true,
            graphs: true,
            fused_bias: true,
            fused_bias_fp32: false,
            chunk: 2,
            recall: None,
            recall_tables: None,
            profile: false,
        }
    }
}

pub trait Engine: Send + Sync {
    fn name(&self) -> String;
    fn dim(&self) -> usize;
    fn n_fields(&self) -> usize;
    /// `codes` is n x n_fields encoder output; `out` receives n x dim embeddings.
    fn embed(&self, codes: &[i32], n: usize, mode: Mode, out: &mut [f32]) -> anyhow::Result<()>;
    /// With Options::profile: time per stage since the last call, largest first (seconds; CPU
    /// sums thread time). Empty otherwise.
    fn profile(&self) -> Vec<(String, f64)> {
        Vec::new()
    }
}

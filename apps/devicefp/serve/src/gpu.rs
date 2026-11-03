//! GPU engine: the same restructured forward pass as [`crate::cpu`], on one CUDA stream.
//!
//! * `precision`: fp32 activations and weights, cuBLAS SGEMM in pedantic math mode, so no TF32
//!   or other reduced-precision algorithm is used even where the hardware has one (Ampere+).
//! * `recall`: fp16 activations and weights, cuBLAS GemmEx on tensor cores with fp32
//!   accumulation; LayerNorm, softmax and the final normalisation compute in fp32.
//!
//! Each (mode, batch-size bucket) is captured once as a CUDA graph, so a call costs one H2D copy,
//! one graph launch and one D2H copy regardless of the ~25 kernels and ~10 GEMMs per tower.
//! Kernels (kernels/v3.cu) are compiled at start-up with NVRTC for the device's architecture.
//!
//! [`Options`] switch the restructuring, the fused attention and the graphs off one at a time, and
//! select the recall-mode variants of the study (int8 GEMMs, fp32/fp16/int8 layer-1 tables).

use std::cell::RefCell;
use std::collections::HashMap;
use std::ffi::c_void;
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result, anyhow, ensure};
use cudarc::cublas::{result as blas, sys as bsys};
use cudarc::cublaslt::{result as lt, sys as ltsys};
use cudarc::driver::{
    CudaContext, CudaEvent, CudaFunction, CudaGraph, CudaSlice, CudaStream, DevicePtr,
    LaunchConfig, PushKernelArg, sys,
};
use cudarc::nvrtc::{CompileOptions, compile_ptx_with_opts};

use crate::model::{Block, Model, Tower};
use crate::{Dtype, Engine, Mode, Options};

const KERNELS: &str = include_str!("../kernels/v3.cu");

pub struct GpuEngine {
    model: Arc<Model>,
    name: String,
    inner: Mutex<Inner>,
}

struct Funcs {
    /// by table type: fp32, fp16, int8
    gather: [CudaFunction; 3],
    attn_full_8: CudaFunction,
    attn_full_16: CudaFunction,
    attn_cls_8: CudaFunction,
    attn_cls_16: CudaFunction,
    layer_norm: CudaFunction,
    bias_act: CudaFunction,
    take_cls: CudaFunction,
    finish: CudaFunction,
    softmax: CudaFunction,
    quant: CudaFunction,
    dequant: CudaFunction,
}

/// One linear layer on the device (CUdeviceptr values), bias and scales in fp32.
#[derive(Clone, Copy)]
struct DevLin {
    /// fp32/fp16: in x out (transposed), row stride `ldw`; int8: out x in, row stride `k`
    w: u64,
    ldw: usize,
    /// int8: one scale per output column
    sw: u64,
    b: u64,
    /// fp16 GEMMs: the bias in fp16 too, for the cuBLASLt epilogue
    bh: u64,
    /// weight element size in bytes (1 = int8)
    es: usize,
    k: usize,
}

impl DevLin {
    /// the layer restricted to output columns c0..
    fn cols(self, c0: usize) -> Self {
        let w = if self.es == 1 {
            self.w + (c0 * self.k) as u64
        } else {
            self.w + (c0 * self.es) as u64
        };
        Self {
            w,
            sw: self.sw + (c0 * 4) as u64,
            b: self.b + (c0 * 4) as u64,
            bh: self.bh + (c0 * 2) as u64,
            ..self
        }
    }
}

struct DevBlock {
    n1_w: u64,
    n1_b: u64,
    /// [q | k | v] outputs
    qkv: DevLin,
    out: DevLin,
    n2_w: u64,
    n2_b: u64,
    w1: DevLin,
    w2: DevLin,
}

/// Layer-1 tables; scale pointers are 0 unless the tables are int8.
struct DevTables {
    kind: usize,
    tok: u64,
    tok_s: u64,
    qkv1: u64,
    qkv1_s: u64,
    cls_tok: u64,
    cls_tok_s: u64,
    cls_qkv1: u64,
    cls_qkv1_s: u64,
}

struct DevTower {
    fi: u64,
    off: u64,
    tab: DevTables,
    l1: DevBlock,
    l2: DevBlock,
    head_ln_w: u64,
    head_ln_b: u64,
    head: DevLin,
}

/// What one mode computes in, and its copy of the weights.
struct Conf {
    act: Dtype,
    gemm: Dtype,
    towers: Vec<DevTower>,
}

struct Buffers {
    codes: u64,
    out: u64,
    x: u64,
    qkv: u64,
    att: u64,
    h: u64,
    f: u64,
    q: u64,
    a: u64,
    c: u64,
    hc: u64,
    fc: u64,
    y: u64,
    /// unfused attention: one head's scores
    s: u64,
    /// Options::fused_bias: scratch output for timing candidate GEMM algorithms
    tune: u64,
    /// int8 GEMMs: quantised activations, their row scales, int32 results
    xq: u64,
    sx: u64,
    acc: u64,
}

struct Inner {
    ctx: Arc<CudaContext>,
    stream: Arc<CudaStream>,
    /// precision (pedantic fp32) and recall (default math, fp16/int8 tensor cores) handles
    blas32: bsys::cublasHandle_t,
    blas16: bsys::cublasHandle_t,
    /// Options::fused_bias: cuBLASLt handle, its workspace, and the chosen algorithm per GEMM shape
    lt: ltsys::cublasLtHandle_t,
    lt_ws: u64,
    lt_algos: RefCell<HashMap<LtKey, ltsys::cublasLtMatmulAlgo_t>>,
    f32k: Funcs,
    f16k: Funcs,
    precision: Conf,
    recall: Conf,
    opts: Options,
    buf: Buffers,
    graphs: HashMap<(Mode, usize), CudaGraph>,
    max_batch: usize,
    staging: Vec<i32>,
    /// Options::profile: an event after each stage, and the milliseconds per stage so far
    marks: RefCell<Vec<(&'static str, CudaEvent)>>,
    stage_ms: HashMap<&'static str, f64>,
    /// owners of every device allocation the raw pointers above point into
    _mem: Vec<CudaSlice<u8>>,
}

/// GEMM shape for the cuBLASLt algorithm cache: fp16?, (m, n, k, lda, ldb, ldc), alignment of
/// the a/b/c pointers, accumulate?, ReLU?
type LtKey = (bool, [usize; 6], [u32; 3], bool, bool);

const WS_BYTES: usize = 32 << 20;

// SAFETY: the cuBLAS handles are only used while holding the Mutex, on the engine's own stream.
unsafe impl Send for Inner {}

fn bytes_of<T>(v: &[T]) -> &[u8] {
    // SAFETY: plain-old-data slices (f32, i32, u16, i8) viewed as bytes.
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

/// Symmetric int8 over chunks of `w` elements, one scale per chunk.
fn quantize_chunks(x: &[f32], w: usize) -> (Vec<i8>, Vec<f32>) {
    let mut q = vec![0i8; x.len()];
    let mut s = vec![0f32; x.len() / w];
    for ((xc, qc), sc) in x.chunks_exact(w).zip(q.chunks_exact_mut(w)).zip(&mut s) {
        let m = xc.iter().fold(0f32, |a, v| a.max(v.abs()));
        *sc = if m > 0.0 { m / 127.0 } else { 1.0 };
        for (o, v) in qc.iter_mut().zip(xc) {
            *o = (v / *sc).round_ties_even() as i8;
        }
    }
    (q, s)
}

struct Uploader<'a> {
    stream: &'a Arc<CudaStream>,
    mem: Vec<CudaSlice<u8>>,
}

impl Uploader<'_> {
    fn bytes(&mut self, b: &[u8]) -> Result<u64> {
        let s = self.stream.clone_htod(b)?;
        let p = s.device_ptr(self.stream).0;
        self.mem.push(s);
        Ok(p)
    }
    fn zeros(&mut self, n: usize) -> Result<u64> {
        let s = self.stream.alloc_zeros::<u8>(n.max(1))?;
        let p = s.device_ptr(self.stream).0;
        self.mem.push(s);
        Ok(p)
    }
    fn f32(&mut self, v: &[f32]) -> Result<u64> {
        self.bytes(bytes_of(v))
    }
    fn i32(&mut self, v: &[i32]) -> Result<u64> {
        self.bytes(bytes_of(v))
    }
    /// fp32 as is, or rounded to fp16 (nearest even)
    fn float(&mut self, v: &[f32], dt: Dtype) -> Result<u64> {
        if dt == Dtype::F16 {
            let h: Vec<u16> = v
                .iter()
                .map(|x| half::f16::from_f32(*x).to_bits())
                .collect();
            self.bytes(bytes_of(&h))
        } else {
            self.f32(v)
        }
    }
    /// `wt` is the transposed weight (k x n row-major)
    fn lin(&mut self, wt: &[f32], k: usize, n: usize, bias: &[f32], dt: Dtype) -> Result<DevLin> {
        let b = self.f32(bias)?;
        let bh = if dt == Dtype::F16 {
            self.float(bias, dt)?
        } else {
            0
        };
        if dt == Dtype::I8 {
            let mut w = vec![0f32; k * n];
            for i in 0..k {
                for j in 0..n {
                    w[j * k + i] = wt[i * n + j];
                }
            }
            let (q, s) = quantize_chunks(&w, k);
            Ok(DevLin {
                w: self.bytes(bytes_of(&q))?,
                ldw: k,
                sw: self.f32(&s)?,
                b,
                bh,
                es: 1,
                k,
            })
        } else {
            Ok(DevLin {
                w: self.float(wt, dt)?,
                ldw: n,
                sw: 0,
                b,
                bh,
                es: if dt == Dtype::F16 { 2 } else { 4 },
                k,
            })
        }
    }
    fn block(&mut self, b: &Block, d: usize, ffn: usize, dt: Dtype) -> Result<DevBlock> {
        Ok(DevBlock {
            n1_w: self.f32(&b.n1_w)?,
            n1_b: self.f32(&b.n1_b)?,
            qkv: self.lin(&b.in_w, d, 3 * d, &b.in_b, dt)?,
            out: self.lin(&b.out_w, d, d, &b.out_b, dt)?,
            n2_w: self.f32(&b.n2_w)?,
            n2_b: self.f32(&b.n2_b)?,
            w1: self.lin(&b.w1, d, ffn, &b.b1, dt)?,
            w2: self.lin(&b.w2, ffn, d, &b.b2, dt)?,
        })
    }
    /// a table and its chunk scales (0 unless int8)
    fn table(&mut self, v: &[f32], d: usize, dt: Dtype) -> Result<(u64, u64)> {
        if dt == Dtype::I8 {
            let (q, s) = quantize_chunks(v, d);
            Ok((self.bytes(bytes_of(&q))?, self.f32(&s)?))
        } else {
            Ok((self.float(v, dt)?, 0))
        }
    }
    fn tower(&mut self, t: &Tower, gemm: Dtype, tab: Dtype) -> Result<DevTower> {
        let fi: Vec<i32> = t.field_idx.iter().map(|&i| i as i32).collect();
        let (tok, tok_s) = self.table(&t.tok, t.d, tab)?;
        let (qkv1, qkv1_s) = self.table(&t.qkv1, t.d, tab)?;
        let (cls_tok, cls_tok_s) = self.table(&t.cls_tok, t.d, tab)?;
        let (cls_qkv1, cls_qkv1_s) = self.table(&t.cls_qkv1, t.d, tab)?;
        let kind = match tab {
            Dtype::F32 => 0,
            Dtype::F16 => 1,
            Dtype::I8 => 2,
        };
        Ok(DevTower {
            fi: self.i32(&fi)?,
            off: self.i32(&t.offsets)?,
            tab: DevTables {
                kind,
                tok,
                tok_s,
                qkv1,
                qkv1_s,
                cls_tok,
                cls_tok_s,
                cls_qkv1,
                cls_qkv1_s,
            },
            l1: self.block(&t.l1, t.d, t.ffn, gemm)?,
            l2: self.block(&t.l2, t.d, t.ffn, gemm)?,
            head_ln_w: self.f32(&t.head_ln_w)?,
            head_ln_b: self.f32(&t.head_ln_b)?,
            head: self.lin(&t.head_w, t.d, t.out, &t.head_b, gemm)?,
        })
    }
}

fn check(s: bsys::cublasStatus_t) -> Result<()> {
    if s == bsys::cublasStatus_t::CUBLAS_STATUS_SUCCESS {
        Ok(())
    } else {
        Err(anyhow!("cuBLAS error {s:?}"))
    }
}

impl GpuEngine {
    pub fn new(model: Arc<Model>, ordinal: usize) -> Result<Self> {
        Self::with_max_batch(model, ordinal, 2048)
    }

    pub fn with_max_batch(model: Arc<Model>, ordinal: usize, max_batch: usize) -> Result<Self> {
        Self::with_options(model, ordinal, max_batch, Options::default())
    }

    pub fn with_options(
        model: Arc<Model>,
        ordinal: usize,
        max_batch: usize,
        opts: Options,
    ) -> Result<Self> {
        ensure!(
            max_batch.is_power_of_two(),
            "max_batch must be a power of two"
        );
        let ctx =
            CudaContext::new(ordinal).context("opening the CUDA device (is libcuda available?)")?;
        // one stream, raw pointers: cudarc's per-allocation event tracking is not needed
        unsafe { ctx.disable_event_tracking() };
        let stream = ctx.new_stream()?;
        let (major, minor) = ctx.compute_capability()?;
        let arch: &'static str = Box::leak(format!("sm_{major}{minor}").into_boxed_str());
        let ptx = compile_ptx_with_opts(
            KERNELS,
            CompileOptions {
                arch: Some(arch),
                use_fast_math: Some(false),
                ..Default::default()
            },
        )
        .map_err(|e| anyhow!("NVRTC failed to compile kernels/v3.cu: {e}"))?;
        let module = ctx.load_module(ptx)?;
        let funcs = |sfx: &str| -> Result<Funcs> {
            let f = |n: &str| {
                module
                    .load_function(&format!("{n}_{sfx}"))
                    .with_context(|| format!("kernel {n}_{sfx}"))
            };
            Ok(Funcs {
                gather: [f("gather_f32")?, f("gather_f16")?, f("gather_i8")?],
                attn_full_8: f("attn_full_8")?,
                attn_full_16: f("attn_full_16")?,
                attn_cls_8: f("attn_cls_8")?,
                attn_cls_16: f("attn_cls_16")?,
                layer_norm: f("layer_norm")?,
                bias_act: f("bias_act")?,
                take_cls: f("take_cls")?,
                finish: f("finish")?,
                softmax: f("softmax_rows")?,
                quant: f("quant_rows")?,
                dequant: f("dequant")?,
            })
        };
        let (f32k, f16k) = (funcs("f32")?, funcs("f16")?);
        for t in &model.towers {
            ensure!(
                t.l <= 1024 && t.d <= 64 && matches!(t.d / t.heads, 8 | 16),
                "tower {}: shape not supported by the GPU kernels",
                t.name
            );
        }

        let rec_gemm = opts.recall.unwrap_or(Dtype::F16);
        let rec_act = if rec_gemm == Dtype::F32 {
            Dtype::F32
        } else {
            Dtype::F16
        };
        let rec_tab = opts.recall_tables.unwrap_or(rec_act);
        let mut up = Uploader {
            stream: &stream,
            mem: Vec::new(),
        };
        let mut conf = |act, gemm, tab| -> Result<Conf> {
            let towers = model
                .towers
                .iter()
                .map(|t| up.tower(t, gemm, tab))
                .collect::<Result<Vec<_>>>()?;
            Ok(Conf { act, gemm, towers })
        };
        let precision = conf(Dtype::F32, Dtype::F32, Dtype::F32)?;
        let recall = conf(rec_act, rec_gemm, rec_tab)?;
        // activation buffers sized for the largest tower in fp32 (fp16 uses half of each)
        let mb = max_batch;
        let lmax = model.towers.iter().map(|t| t.l).max().unwrap();
        let tokens = model.towers.iter().map(|t| t.l * t.d).max().unwrap();
        let ffn_tokens = model.towers.iter().map(|t| t.l * t.ffn).max().unwrap();
        let dmax = model.towers.iter().map(|t| t.d.max(t.out)).max().unwrap();
        let fmax = model.towers.iter().map(|t| t.ffn).max().unwrap();
        let wide = model
            .towers
            .iter()
            .map(|t| t.ffn.max(3 * t.d))
            .max()
            .unwrap();
        let int8 = rec_gemm == Dtype::I8;
        let buf = Buffers {
            codes: up.zeros(mb * model.n_fields * 4)?,
            out: up.zeros(mb * model.dim * 4)?,
            x: up.zeros(mb * tokens * 4)?,
            qkv: up.zeros(mb * tokens * 3 * 4)?,
            att: up.zeros(mb * tokens * 4)?,
            h: up.zeros(mb * tokens * 4)?,
            f: up.zeros(mb * ffn_tokens * 4)?,
            q: up.zeros(mb * dmax * 4)?,
            a: up.zeros(mb * dmax * 4)?,
            c: up.zeros(mb * dmax * 4)?,
            hc: up.zeros(mb * dmax * 4)?,
            fc: up.zeros(mb * fmax * 4)?,
            y: up.zeros(mb * dmax * 4)?,
            s: up.zeros(if opts.fused_attn {
                0
            } else {
                mb * lmax * lmax * 4
            })?,
            xq: up.zeros(if int8 { mb * lmax * wide } else { 0 })?,
            sx: up.zeros(if int8 { mb * lmax * 4 } else { 0 })?,
            acc: up.zeros(if int8 { mb * lmax * wide * 4 } else { 0 })?,
            tune: up.zeros(if opts.fused_bias || opts.fused_bias_fp32 {
                mb * lmax * wide * 4
            } else {
                0
            })?,
        };
        // cuBLAS must not allocate while a graph is being captured: give it a fixed workspace
        let ws_bytes = 32 << 20;
        let ws32 = up.zeros(ws_bytes)?;
        let ws16 = up.zeros(ws_bytes)?;
        let lt_ws = up.zeros(WS_BYTES)?;
        let mem = up.mem;
        let mk = |math: bsys::cublasMath_t, ws: u64| -> Result<bsys::cublasHandle_t> {
            let h = blas::create_handle()?;
            unsafe {
                blas::set_stream(h, stream.cu_stream() as _)?;
                check(bsys::cublasSetMathMode(h, math))?;
                check(bsys::cublasSetWorkspace_v2(h, ws as *mut c_void, ws_bytes))?;
            }
            Ok(h)
        };
        let blas32 = mk(bsys::cublasMath_t::CUBLAS_PEDANTIC_MATH, ws32)?;
        let blas16 = mk(bsys::cublasMath_t::CUBLAS_DEFAULT_MATH, ws16)?;
        let lt_handle = lt::create_handle()?;
        stream.synchronize()?;
        let name = format!("gpu ({}, {arch})", ctx.name()?);
        let inner = Inner {
            ctx,
            stream,
            blas32,
            blas16,
            lt: lt_handle,
            lt_ws,
            lt_algos: RefCell::default(),
            f32k,
            f16k,
            precision,
            recall,
            opts,
            buf,
            graphs: HashMap::new(),
            max_batch,
            staging: Vec::new(),
            marks: RefCell::default(),
            stage_ms: HashMap::new(),
            _mem: mem,
        };
        Ok(Self {
            model,
            name,
            inner: Mutex::new(inner),
        })
    }
}

/// launch!(inner, kernel, (grid_x, grid_y), block, shared_bytes; &arg, &arg, ...)
macro_rules! launch {
    ($inner:expr, $f:expr, $grid:expr, $block:expr, $shmem:expr; $($arg:expr),* $(,)?) => {{
        let mut b = $inner.stream.launch_builder($f);
        $( b.arg($arg); )*
        let (gx, gy): (u32, u32) = $grid;
        let cfg = LaunchConfig { grid_dim: (gx, gy, 1), block_dim: ($block, 1, 1), shared_mem_bytes: $shmem };
        // SAFETY: argument order and types match the kernel signatures in kernels/v3.cu
        unsafe { b.launch(cfg) }.map(|_| ()).map_err(anyhow::Error::from)
    }};
}

fn cuda_type(dt: Dtype) -> bsys::cudaDataType {
    match dt {
        Dtype::F32 => bsys::cudaDataType::CUDA_R_32F,
        Dtype::F16 => bsys::cudaDataType::CUDA_R_16F,
        Dtype::I8 => bsys::cudaDataType::CUDA_R_8I,
    }
}

impl Inner {
    /// Options::profile: charges the GPU time since the previous mark to `stage`.
    fn mark(&self, stage: &'static str) -> Result<()> {
        if self.opts.profile {
            let ev = self
                .stream
                .record_event(Some(sys::CUevent_flags::CU_EVENT_DEFAULT))?;
            self.marks.borrow_mut().push((stage, ev));
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    /// Row-major c[m x n] = a[m x k] * b[k x n] + beta * c (column-major cuBLAS on transposes),
    /// in fp32 (pedantic) or fp16 (tensor cores, fp32 accumulation).
    fn gemm(
        &self,
        dt: Dtype,
        m: usize,
        n: usize,
        k: usize,
        a: u64,
        lda: usize,
        b: u64,
        ldb: usize,
        c: u64,
        ldc: usize,
        beta: f32,
    ) -> Result<()> {
        let (alpha, op) = (1.0f32, bsys::cublasOperation_t::CUBLAS_OP_N);
        let (m, n, k, lda, ldb, ldc) = (
            m as i32, n as i32, k as i32, lda as i32, ldb as i32, ldc as i32,
        );
        unsafe {
            match dt {
                Dtype::F32 => blas::sgemm(
                    self.blas32,
                    op,
                    op,
                    n,
                    m,
                    k,
                    &alpha,
                    b as *const f32,
                    ldb,
                    a as *const f32,
                    lda,
                    &beta,
                    c as *mut f32,
                    ldc,
                )?,
                _ => {
                    let h = bsys::cudaDataType::CUDA_R_16F;
                    blas::gemm_ex(
                        self.blas16,
                        op,
                        op,
                        n,
                        m,
                        k,
                        &alpha as *const f32 as *const c_void,
                        b as *const c_void,
                        h,
                        ldb,
                        a as *const c_void,
                        h,
                        lda,
                        &beta as *const f32 as *const c_void,
                        c as *mut c_void,
                        h,
                        ldc,
                        bsys::cublasComputeType_t::CUBLAS_COMPUTE_32F,
                        bsys::cublasGemmAlgo_t::CUBLAS_GEMM_DEFAULT,
                    )?
                }
            }
        }
        Ok(())
    }

    /// Like [`Self::gemm`] plus `bias` (fp32, length n) and an optional ReLU in the cuBLASLt
    /// epilogue: c = act(a b + beta c + bias).
    #[allow(clippy::too_many_arguments)]
    fn gemm_lt(
        &self,
        dt: Dtype,
        m: usize,
        n: usize,
        k: usize,
        a: u64,
        lda: usize,
        b: u64,
        ldb: usize,
        c: u64,
        ldc: usize,
        beta: f32,
        bias: u64,
        relu: bool,
    ) -> Result<()> {
        use ltsys::cublasLtMatmulDescAttributes_t as D;
        let half = dt != Dtype::F32;
        let ty = if half {
            ltsys::cudaDataType::CUDA_R_16F
        } else {
            ltsys::cudaDataType::CUDA_R_32F
        };
        let align = |p: u64| p.isolate_lowest_one().min(256) as u32;
        let key: LtKey = (
            half,
            [m, n, k, lda, ldb, ldc],
            [align(a), align(b), align(c)],
            beta != 0.0,
            relu,
        );
        let alpha = 1.0f32;
        // column-major view as in `gemm`: C^T[n x m] = W^T[n x k] * X^T[k x m]; the bias runs
        // along the n output features, the rows of C^T
        unsafe {
            let desc = lt::create_matmul_desc(
                ltsys::cublasComputeType_t::CUBLAS_COMPUTE_32F,
                ltsys::cudaDataType::CUDA_R_32F,
            )?;
            let epi = if relu {
                ltsys::cublasLtEpilogue_t::CUBLASLT_EPILOGUE_RELU_BIAS
            } else {
                ltsys::cublasLtEpilogue_t::CUBLASLT_EPILOGUE_BIAS
            };
            let set =
                |attr, v: *const c_void, size| lt::set_matmul_desc_attribute(desc, attr, v, size);
            set(
                D::CUBLASLT_MATMUL_DESC_EPILOGUE,
                &epi as *const _ as *const c_void,
                4,
            )?;
            let bp = bias as *const c_void;
            set(
                D::CUBLASLT_MATMUL_DESC_BIAS_POINTER,
                &bp as *const _ as *const c_void,
                8,
            )?;
            if !half {
                let bt = ltsys::cudaDataType::CUDA_R_32F;
                set(
                    D::CUBLASLT_MATMUL_DESC_BIAS_DATA_TYPE,
                    &bt as *const _ as *const c_void,
                    4,
                )?;
            }
            let la = lt::create_matrix_layout(ty, n as u64, k as u64, ldb as i64)?;
            let lb = lt::create_matrix_layout(ty, k as u64, m as u64, lda as i64)?;
            let lc = lt::create_matrix_layout(ty, n as u64, m as u64, ldc as i64)?;
            let cached = self.lt_algos.borrow().get(&key).copied();
            let algo = match cached {
                Some(algo) => algo,
                None => {
                    let algo = self.tune_lt(desc, (la, lb, lc), key, (a, b, c), beta)?;
                    self.lt_algos.borrow_mut().insert(key, algo);
                    algo
                }
            };
            lt::matmul(
                self.lt,
                desc,
                &alpha as *const f32 as *const c_void,
                &beta as *const f32 as *const c_void,
                b as *const c_void,
                la,
                a as *const c_void,
                lb,
                c as *const c_void,
                lc,
                c as *mut c_void,
                lc,
                &algo,
                self.lt_ws as *mut c_void,
                WS_BYTES,
                self.stream.cu_stream() as ltsys::cudaStream_t,
            )?;
            for l in [la, lb, lc] {
                lt::destroy_matrix_layout(l)?;
            }
            lt::destroy_matmul_desc(desc)?;
        }
        Ok(())
    }

    /// Picks the fastest of cuBLASLt's top heuristic candidates for this GEMM by timing each on
    /// the real inputs, writing into the scratch buffer so `c` is left untouched.
    unsafe fn tune_lt(
        &self,
        desc: ltsys::cublasLtMatmulDesc_t,
        (la, lb, lc): (
            ltsys::cublasLtMatrixLayout_t,
            ltsys::cublasLtMatrixLayout_t,
            ltsys::cublasLtMatrixLayout_t,
        ),
        key: LtKey,
        (a, b, c): (u64, u64, u64),
        beta: f32,
    ) -> Result<ltsys::cublasLtMatmulAlgo_t> {
        use ltsys::cublasLtMatmulPreferenceAttributes_t as P;
        unsafe {
            let pref = lt::create_matmul_pref()?;
            let setp =
                |attr, v: *const c_void, size| lt::set_matmul_pref_attribute(pref, attr, v, size);
            let ws = WS_BYTES as u64;
            setp(
                P::CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES,
                &ws as *const _ as *const c_void,
                8,
            )?;
            for (attr, al) in [
                (P::CUBLASLT_MATMUL_PREF_MIN_ALIGNMENT_A_BYTES, key.2[1]),
                (P::CUBLASLT_MATMUL_PREF_MIN_ALIGNMENT_B_BYTES, key.2[0]),
                (P::CUBLASLT_MATMUL_PREF_MIN_ALIGNMENT_C_BYTES, key.2[2]),
                (P::CUBLASLT_MATMUL_PREF_MIN_ALIGNMENT_D_BYTES, key.2[2]),
            ] {
                setp(attr, &al as *const _ as *const c_void, 4)?;
            }
            let mut res: [ltsys::cublasLtMatmulHeuristicResult_t; 8] = std::mem::zeroed();
            let mut count = 0;
            let st = ltsys::cublasLtMatmulAlgoGetHeuristic(
                self.lt,
                desc,
                la,
                lb,
                lc,
                lc,
                pref,
                res.len() as i32,
                res.as_mut_ptr(),
                &mut count,
            );
            lt::destroy_matmul_pref(pref)?;
            ensure!(
                st == ltsys::cublasStatus_t::CUBLAS_STATUS_SUCCESS && count > 0,
                "no cuBLASLt algorithm for {key:?}: {st:?}"
            );
            let alpha = 1.0f32;
            let run = |algo: &ltsys::cublasLtMatmulAlgo_t| {
                lt::matmul(
                    self.lt,
                    desc,
                    &alpha as *const f32 as *const c_void,
                    &beta as *const f32 as *const c_void,
                    b as *const c_void,
                    la,
                    a as *const c_void,
                    lb,
                    c as *const c_void,
                    lc,
                    self.buf.tune as *mut c_void,
                    lc,
                    algo,
                    self.lt_ws as *mut c_void,
                    WS_BYTES,
                    self.stream.cu_stream() as ltsys::cudaStream_t,
                )
            };
            let mut best = (f32::INFINITY, res[0].algo);
            for r in &res[..count as usize] {
                if r.state != ltsys::cublasStatus_t::CUBLAS_STATUS_SUCCESS || run(&r.algo).is_err()
                {
                    continue;
                }
                let ev =
                    |s: &CudaStream| s.record_event(Some(sys::CUevent_flags::CU_EVENT_DEFAULT));
                let t0 = ev(&self.stream)?;
                for _ in 0..5 {
                    run(&r.algo)?;
                }
                let ms = t0.elapsed_ms(&ev(&self.stream)?)?;
                if ms < best.0 {
                    best = (ms, r.algo);
                }
            }
            Ok(best.1)
        }
    }

    /// out[rows x n] (+)= x[rows x k] W + b, ReLU if asked, in the configuration's GEMM type.
    #[allow(clippy::too_many_arguments)]
    fn linear(
        &self,
        conf: &Conf,
        kf: &Funcs,
        rows: usize,
        n: usize,
        x: u64,
        ldx: usize,
        lin: DevLin,
        out: u64,
        ldo: usize,
        accumulate: bool,
        relu: bool,
    ) -> Result<()> {
        let k = lin.k;
        if conf.gemm != Dtype::I8 {
            let beta = if accumulate { 1.0 } else { 0.0 };
            let fuse = match conf.gemm {
                Dtype::F16 => self.opts.fused_bias,
                _ => self.opts.fused_bias_fp32,
            };
            if fuse {
                let bias = if conf.gemm == Dtype::F16 {
                    lin.bh
                } else {
                    lin.b
                };
                self.gemm_lt(
                    conf.gemm, rows, n, k, x, ldx, lin.w, lin.ldw, out, ldo, beta, bias, relu,
                )?;
                return self.mark("GEMM");
            }
            self.gemm(
                conf.gemm, rows, n, k, x, ldx, lin.w, lin.ldw, out, ldo, beta,
            )?;
            self.mark("GEMM")?;
            self.bias(kf, out, ldo, lin.b, n, rows, relu)?;
            return self.mark("bias + activation");
        }
        let bf = &self.buf;
        let (ldx_i, rows_i, k_i) = (ldx as i32, rows as i32, k as i32);
        launch!(self, &kf.quant, ((rows as u32).div_ceil(8), 1), 256, 0; &x, &ldx_i, &bf.xq, &bf.sx, &rows_i, &k_i)?;
        self.mark("int8 quantise")?;
        // int32 C^T[n x rows] = W8[n x k] (stored k-major: op T) * Xq^T[k x rows]
        let (one, zero) = (1i32, 0i32);
        unsafe {
            blas::gemm_ex(
                self.blas16,
                bsys::cublasOperation_t::CUBLAS_OP_T,
                bsys::cublasOperation_t::CUBLAS_OP_N,
                n as i32,
                rows as i32,
                k as i32,
                &one as *const i32 as *const c_void,
                lin.w as *const c_void,
                cuda_type(Dtype::I8),
                lin.ldw as i32,
                bf.xq as *const c_void,
                cuda_type(Dtype::I8),
                k as i32,
                &zero as *const i32 as *const c_void,
                bf.acc as *mut c_void,
                bsys::cudaDataType::CUDA_R_32I,
                n as i32,
                bsys::cublasComputeType_t::CUBLAS_COMPUTE_32I,
                bsys::cublasGemmAlgo_t::CUBLAS_GEMM_DEFAULT,
            )?;
        }
        self.mark("GEMM")?;
        let total = (rows * n) as i64;
        let (n_i, ldo_i, acc_i, relu_i) = (n as i32, ldo as i32, accumulate as i32, relu as i32);
        launch!(self, &kf.dequant, ((total as u32).div_ceil(256), 1), 256, 0; &bf.acc, &n_i, &bf.sx, &lin.sw, &lin.b, &out, &ldo_i, &total, &acc_i, &relu_i)?;
        self.mark("int8 dequantise + bias")
    }

    #[allow(clippy::too_many_arguments)]
    fn bias(
        &self,
        k: &Funcs,
        x: u64,
        ld: usize,
        bias: u64,
        n: usize,
        rows: usize,
        relu: bool,
    ) -> Result<()> {
        let total = (rows * n) as i64;
        let (ld, n, relu) = (ld as i32, n as i32, relu as i32);
        launch!(self, &k.bias_act, ((total as u32).div_ceil(256), 1), 256, 0; &x, &ld, &bias, &n, &total, &relu)
    }

    #[allow(clippy::too_many_arguments)]
    fn ln(
        &self,
        k: &Funcs,
        x: u64,
        ld_in: usize,
        y: u64,
        w: u64,
        b: u64,
        rows: usize,
        d: usize,
        eps: f32,
    ) -> Result<()> {
        let (ld_in, rows_i, d) = (ld_in as i32, rows as i32, d as i32);
        launch!(self, &k.layer_norm, ((rows as u32).div_ceil(8), 1), 256, 0; &x, &ld_in, &y, &w, &b, &rows_i, &d, &eps)?;
        self.mark("layernorm")
    }

    /// Attention without the fused kernels: per head, S = Q K^T / sqrt(dh) and O = softmax(S) V
    /// as cuBLAS strided-batched GEMMs over the profiles, with a softmax kernel in between.
    /// q: `lq` rows per profile (stride ldq, profile stride sq); k/v: `l` rows (stride ldkv,
    /// profile stride skv); out: `lq` rows (stride ldo, profile stride so). Pointers at head 0.
    #[allow(clippy::too_many_arguments)]
    fn attention_gemm(
        &self,
        act: Dtype,
        kf: &Funcs,
        b: usize,
        heads: usize,
        dh: usize,
        lq: usize,
        l: usize,
        (q, ldq, sq): (u64, usize, usize),
        (kp, vp, ldkv, skv): (u64, u64, usize, usize),
        (o, ldo, so): (u64, usize, usize),
    ) -> Result<()> {
        let es = if act == Dtype::F32 { 4 } else { 2 };
        let s = self.buf.s;
        let (op_n, op_t) = (
            bsys::cublasOperation_t::CUBLAS_OP_N,
            bsys::cublasOperation_t::CUBLAS_OP_T,
        );
        let scale = 1.0 / (dh as f32).sqrt();
        let (one, zero) = (1.0f32, 0.0f32);
        let (lq_i, l_i, dh_i, b_i) = (lq as i32, l as i32, dh as i32, b as i32);
        for h in 0..heads {
            let off = (h * dh * es) as u64;
            // column-major: S^T[l x lq] = K_h (op T on the dh x l view) * Q_h^T
            // then O^T[dh x lq] = V_h^T * P^T
            unsafe {
                if act == Dtype::F32 {
                    blas::sgemm_strided_batched(
                        self.blas32,
                        op_t,
                        op_n,
                        l_i,
                        lq_i,
                        dh_i,
                        &scale,
                        (kp + off) as *const f32,
                        ldkv as i32,
                        skv as i64,
                        (q + off) as *const f32,
                        ldq as i32,
                        sq as i64,
                        &zero,
                        s as *mut f32,
                        l_i,
                        (lq * l) as i64,
                        b_i,
                    )?;
                } else {
                    let t = cuda_type(act);
                    blas::gemm_strided_batched_ex(
                        self.blas16,
                        op_t,
                        op_n,
                        l_i,
                        lq_i,
                        dh_i,
                        &scale as *const f32 as *const c_void,
                        (kp + off) as *const c_void,
                        t,
                        ldkv as i32,
                        skv as i64,
                        (q + off) as *const c_void,
                        t,
                        ldq as i32,
                        sq as i64,
                        &zero as *const f32 as *const c_void,
                        s as *mut c_void,
                        t,
                        l_i,
                        (lq * l) as i64,
                        b_i,
                        bsys::cublasComputeType_t::CUBLAS_COMPUTE_32F,
                        bsys::cublasGemmAlgo_t::CUBLAS_GEMM_DEFAULT,
                    )?;
                }
            }
            let rows = (b * lq) as i64;
            launch!(self, &kf.softmax, ((rows as u32).div_ceil(8), 1), 256, 0; &s, &rows, &l_i)?;
            unsafe {
                if act == Dtype::F32 {
                    blas::sgemm_strided_batched(
                        self.blas32,
                        op_n,
                        op_n,
                        dh_i,
                        lq_i,
                        l_i,
                        &one,
                        (vp + off) as *const f32,
                        ldkv as i32,
                        skv as i64,
                        s as *const f32,
                        l_i,
                        (lq * l) as i64,
                        &zero,
                        (o + off) as *mut f32,
                        ldo as i32,
                        so as i64,
                        b_i,
                    )?;
                } else {
                    let t = cuda_type(act);
                    blas::gemm_strided_batched_ex(
                        self.blas16,
                        op_n,
                        op_n,
                        dh_i,
                        lq_i,
                        l_i,
                        &one as *const f32 as *const c_void,
                        (vp + off) as *const c_void,
                        t,
                        ldkv as i32,
                        skv as i64,
                        s as *const c_void,
                        t,
                        l_i,
                        (lq * l) as i64,
                        &zero as *const f32 as *const c_void,
                        (o + off) as *mut c_void,
                        t,
                        ldo as i32,
                        so as i64,
                        b_i,
                        bsys::cublasComputeType_t::CUBLAS_COMPUTE_32F,
                        bsys::cublasGemmAlgo_t::CUBLAS_GEMM_DEFAULT,
                    )?;
                }
            }
        }
        self.mark("attention")
    }

    /// Self-attention over every token: qkv (rows [q | k | v], width 3d) -> att (width d).
    fn attention_full(&self, conf: &Conf, kf: &Funcs, t: &Tower, b: usize) -> Result<()> {
        let (d, l, heads) = (t.d, t.l, t.heads);
        let dh = d / heads;
        let bf = &self.buf;
        if self.opts.fused_attn {
            let f = if dh == 16 {
                &kf.attn_full_16
            } else {
                &kf.attn_full_8
            };
            let (l_i, d_i) = (l as i32, d as i32);
            let threads = (l as u32).div_ceil(32) * 32;
            launch!(self, f, (b as u32, heads as u32), threads, (2 * l * dh * 4) as u32; &bf.qkv, &bf.att, &l_i, &d_i)?;
            return self.mark("attention");
        }
        let es = if conf.act == Dtype::F32 { 4 } else { 2 };
        let w = 3 * d;
        self.attention_gemm(
            conf.act,
            kf,
            b,
            heads,
            dh,
            l,
            l,
            (bf.qkv, w, l * w),
            (
                bf.qkv + (d * es) as u64,
                bf.qkv + (2 * d * es) as u64,
                w,
                l * w,
            ),
            (bf.att, d, l * d),
        )
    }

    /// x += out_proj(att); x += FFN(LN2(x)), over `rows` rows of width d
    #[allow(clippy::too_many_arguments)]
    fn rest_of_layer(
        &self,
        conf: &Conf,
        kf: &Funcs,
        blk: &DevBlock,
        t: &Tower,
        eps: f32,
        rows: usize,
        (att, x, h, f): (u64, u64, u64, u64),
    ) -> Result<()> {
        let (d, ffn) = (t.d, t.ffn);
        self.linear(conf, kf, rows, d, att, d, blk.out, x, d, true, false)?;
        self.ln(kf, x, d, h, blk.n2_w, blk.n2_b, rows, d, eps)?;
        self.linear(conf, kf, rows, ffn, h, d, blk.w1, f, ffn, false, true)?;
        self.linear(conf, kf, rows, d, f, ffn, blk.w2, x, d, true, false)
    }

    /// Issues the whole forward pass for `b` profiles (codes already in `buf.codes`).
    fn record(&self, m: &Model, b: usize, mode: Mode) -> Result<()> {
        let conf = match mode {
            Mode::Precision => &self.precision,
            Mode::Recall => &self.recall,
        };
        let (k, es) = match conf.act {
            Dtype::F32 => (&self.f32k, 4usize),
            _ => (&self.f16k, 2usize),
        };
        let bf = &self.buf;
        let eps = m.eps;
        let o = &self.opts;
        for (t, g) in m.towers.iter().zip(&conf.towers) {
            let (d, l) = (t.d, t.l);
            let dh = d / t.heads;
            let bl = b * l;
            let (nf, l_i, d_i) = (m.n_fields as i32, l as i32, d as i32);
            let tb = &g.tab;
            let with_qkv = o.tables as i32;
            launch!(self, &k.gather[tb.kind], (bl as u32, 1), 64, 0; &bf.codes, &nf, &g.fi, &g.off, &l_i, &tb.tok, &tb.tok_s, &tb.qkv1, &tb.qkv1_s, &tb.cls_tok, &tb.cls_tok_s, &tb.cls_qkv1, &tb.cls_qkv1_s, &d_i, &bf.x, &bf.qkv, &with_qkv)?;
            self.mark("gather")?;
            if !o.tables {
                self.ln(k, bf.x, d, bf.h, g.l1.n1_w, g.l1.n1_b, bl, d, eps)?;
                self.linear(
                    conf,
                    k,
                    bl,
                    3 * d,
                    bf.h,
                    d,
                    g.l1.qkv,
                    bf.qkv,
                    3 * d,
                    false,
                    false,
                )?;
            }
            self.attention_full(conf, k, t, b)?;
            self.rest_of_layer(conf, k, &g.l1, t, eps, bl, (bf.att, bf.x, bf.h, bf.f))?;

            let k2 = &g.l2;
            self.ln(k, bf.x, d, bf.h, k2.n1_w, k2.n1_b, bl, d, eps)?;
            let total = (b * d) as i64;
            if o.cls_only {
                // layer 2: K/V for all tokens, the rest for CLS rows only
                let kv = bf.qkv;
                self.linear(
                    conf,
                    k,
                    bl,
                    2 * d,
                    bf.h,
                    d,
                    k2.qkv.cols(d),
                    kv,
                    2 * d,
                    false,
                    false,
                )?;
                self.linear(conf, k, b, d, bf.h, l * d, k2.qkv, bf.q, d, false, false)?;
                if o.fused_attn {
                    let one = if dh == 16 {
                        &k.attn_cls_16
                    } else {
                        &k.attn_cls_8
                    };
                    launch!(self, one, (b as u32, 1), (t.heads * 32) as u32, 0; &bf.q, &kv, &bf.a, &l_i, &d_i)?;
                    self.mark("attention")?;
                } else {
                    self.attention_gemm(
                        conf.act,
                        k,
                        b,
                        t.heads,
                        dh,
                        1,
                        l,
                        (bf.q, d, d),
                        (kv, kv + (d * es) as u64, 2 * d, l * 2 * d),
                        (bf.a, d, d),
                    )?;
                }
                launch!(self, &k.take_cls, ((total as u32).div_ceil(256), 1), 256, 0; &bf.x, &bf.c, &l_i, &d_i, &total)?;
                self.mark("other")?;
                self.rest_of_layer(conf, k, k2, t, eps, b, (bf.a, bf.c, bf.hc, bf.fc))?;
            } else {
                // the full second layer, then the CLS rows
                self.linear(
                    conf,
                    k,
                    bl,
                    3 * d,
                    bf.h,
                    d,
                    k2.qkv,
                    bf.qkv,
                    3 * d,
                    false,
                    false,
                )?;
                self.attention_full(conf, k, t, b)?;
                self.rest_of_layer(conf, k, k2, t, eps, bl, (bf.att, bf.x, bf.h, bf.f))?;
                launch!(self, &k.take_cls, ((total as u32).div_ceil(256), 1), 256, 0; &bf.x, &bf.c, &l_i, &d_i, &total)?;
                self.mark("other")?;
            }

            // head: LayerNorm, Linear, unit length * sqrt(w), written as fp32 into its columns
            self.ln(k, bf.c, d, bf.hc, g.head_ln_w, g.head_ln_b, b, d, eps)?;
            self.linear(
                conf, k, b, t.out, bf.hc, d, g.head, bf.y, t.out, false, false,
            )?;
            let (n_i, dim_i, col_i, rows_i) = (t.out as i32, m.dim as i32, t.col as i32, b as i32);
            launch!(self, &k.finish, ((b as u32).div_ceil(8), 1), 256, 0; &bf.y, &n_i, &bf.out, &dim_i, &col_i, &t.scale, &rows_i)?;
            self.mark("other")?;
        }
        Ok(())
    }

    fn graph(&mut self, m: &Model, bucket: usize, mode: Mode) -> Result<&CudaGraph> {
        if !self.graphs.contains_key(&(mode, bucket)) {
            if self.opts.fused_bias || self.opts.fused_bias_fp32 {
                // one direct pass first: GEMM algorithms are timed outside the capture
                self.record(m, bucket, mode)?;
            }
            self.stream
                .begin_capture(sys::CUstreamCaptureMode::CU_STREAM_CAPTURE_MODE_THREAD_LOCAL)?;
            let rec = self.record(m, bucket, mode);
            let g = self.stream.end_capture(sys::CUgraphInstantiate_flags(0))?;
            rec?;
            let g = g.context("graph capture produced no graph")?;
            g.upload()?;
            self.graphs.insert((mode, bucket), g);
        }
        Ok(&self.graphs[&(mode, bucket)])
    }
}

impl Engine for GpuEngine {
    fn name(&self) -> String {
        self.name.clone()
    }

    fn dim(&self) -> usize {
        self.model.dim
    }

    fn n_fields(&self) -> usize {
        self.model.n_fields
    }

    fn embed(&self, codes: &[i32], n: usize, mode: Mode, out: &mut [f32]) -> Result<()> {
        let m = &*self.model;
        let (nf, dim) = (m.n_fields, m.dim);
        ensure!(
            codes.len() == n * nf && out.len() == n * dim,
            "embed: buffer sizes do not match {n} profiles"
        );
        let mut g = self
            .inner
            .lock()
            .map_err(|_| anyhow!("GPU engine poisoned by an earlier panic"))?;
        let inner = &mut *g;
        inner.ctx.bind_to_thread()?;
        let mut staging = std::mem::take(&mut inner.staging);
        for start in (0..n).step_by(inner.max_batch) {
            let b = (n - start).min(inner.max_batch);
            // pad to the graph's bucket with code 0 (a valid "missing" token); padded rows are dropped
            let bucket = b.next_power_of_two();
            staging.clear();
            staging.extend_from_slice(&codes[start * nf..(start + b) * nf]);
            staging.resize(bucket * nf, 0);
            unsafe {
                sys::cuMemcpyHtoDAsync_v2(
                    inner.buf.codes,
                    staging.as_ptr() as *const c_void,
                    staging.len() * 4,
                    inner.stream.cu_stream(),
                )
                .result()?;
            }
            if inner.opts.profile {
                // per-stage events cannot live in a graph: launch directly, then sum the intervals
                inner.mark("copy in")?;
                inner.record(m, bucket, mode)?;
                inner.stream.synchronize()?;
                let marks = std::mem::take(&mut *inner.marks.borrow_mut());
                for w in marks.windows(2) {
                    let ms = w[0].1.elapsed_ms(&w[1].1)? as f64;
                    *inner.stage_ms.entry(w[1].0).or_default() += ms;
                }
            } else if inner.opts.graphs {
                inner.graph(m, bucket, mode)?.launch()?;
            } else {
                inner.record(m, bucket, mode)?;
            }
            unsafe {
                sys::cuMemcpyDtoHAsync_v2(
                    out[start * dim..].as_mut_ptr() as *mut c_void,
                    inner.buf.out,
                    b * dim * 4,
                    inner.stream.cu_stream(),
                )
                .result()?;
            }
            inner.stream.synchronize()?;
        }
        inner.staging = staging;
        Ok(())
    }

    fn profile(&self) -> Vec<(String, f64)> {
        let Ok(mut g) = self.inner.lock() else {
            return Vec::new();
        };
        let mut v: Vec<_> = g
            .stage_ms
            .drain()
            .map(|(k, ms)| (k.to_string(), ms / 1e3))
            .collect();
        v.sort_by(|a, b| b.1.total_cmp(&a.1));
        v
    }
}

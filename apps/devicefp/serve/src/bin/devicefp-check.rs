//! Parity checks against the golden files written by `python -m devicefp.export`.
//!
//!     devicefp-check encode --bundle DIR             every profile's codes == the training codes
//!     devicefp-check embed --bundle DIR --engine cpu --mode precision [--out FILE]
//!                                                    test-split embeddings vs PyTorch fp32
//!     devicefp-check sweep --bundle DIR --engine gpu --batches 1,16,256
//!                                                    latency and throughput per batch size
//!
//! `embed` and `sweep` take the variant flags of the optimisation study (--no-tables,
//! --recall i8, ...); `--json` prints one result object per line.

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand, ValueEnum};
use devicefp_serve::bundle::Bundle;
use devicefp_serve::cpu::CpuEngine;
use devicefp_serve::encoder::{Encoder, Profile};
use devicefp_serve::model::Model;
use devicefp_serve::{Dtype, Engine, Mode, Options};
use rayon::prelude::*;

#[derive(Parser)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    Encode {
        #[arg(long)]
        bundle: PathBuf,
    },
    Embed {
        #[command(flatten)]
        e: EngineArgs,
        /// write the embeddings here (f32 little-endian, test rows x dim)
        #[arg(long)]
        out: Option<PathBuf>,
        #[arg(long, default_value_t = 4096)]
        batch: usize,
        /// timed passes over the test split (the median is reported)
        #[arg(long, default_value_t = 1)]
        repeat: usize,
    },
    Sweep {
        #[command(flatten)]
        e: EngineArgs,
        #[arg(
            long,
            value_delimiter = ',',
            default_value = "1,2,4,8,16,32,64,128,256,512,1024,2048,4096"
        )]
        batches: Vec<usize>,
        /// time spent per batch size (seconds)
        #[arg(long, default_value_t = 2.0)]
        secs: f64,
    },
}

#[derive(clap::Args)]
struct EngineArgs {
    #[arg(long)]
    bundle: PathBuf,
    #[arg(long, value_enum, default_value = "cpu")]
    engine: EngineKind,
    #[arg(long, value_enum, default_value = "precision")]
    mode: ModeArg,
    /// a name for this variant in --json output
    #[arg(long, default_value = "")]
    label: String,
    #[arg(long)]
    json: bool,
    /// compute layer-1 Q/K/V per token instead of gathering them from tables
    #[arg(long)]
    no_tables: bool,
    /// run layer 2 for every token instead of the CLS row only
    #[arg(long)]
    no_cls_only: bool,
    /// GPU: attention as cuBLAS GEMMs + softmax instead of the fused kernels
    #[arg(long)]
    no_fused_attn: bool,
    /// GPU: launch kernels on every call instead of replaying CUDA graphs
    #[arg(long)]
    no_graphs: bool,
    /// GPU: bias and ReLU of fp16 GEMMs as a separate kernel instead of the cuBLASLt epilogue
    #[arg(long)]
    no_fused_bias: bool,
    /// GPU: bias and ReLU of fp32 GEMMs in the cuBLASLt epilogue
    #[arg(long)]
    fused_bias_fp32: bool,
    /// CPU: profiles per thread task
    #[arg(long, default_value_t = 2)]
    chunk: usize,
    /// recall-mode compute type (default: GPU f16, CPU f32)
    #[arg(long, value_enum)]
    recall: Option<DtypeArg>,
    /// recall-mode layer-1 table storage (default: the recall activation type)
    #[arg(long, value_enum)]
    recall_tables: Option<DtypeArg>,
    /// time each stage of the forward pass (GPU: without CUDA graphs)
    #[arg(long)]
    profile: bool,
    /// GPU: largest batch per engine call (power of two)
    #[arg(long, default_value_t = 2048)]
    max_batch: usize,
}

#[derive(Clone, Copy, ValueEnum)]
enum DtypeArg {
    F32,
    F16,
    I8,
}

impl From<DtypeArg> for Dtype {
    fn from(d: DtypeArg) -> Self {
        match d {
            DtypeArg::F32 => Dtype::F32,
            DtypeArg::F16 => Dtype::F16,
            DtypeArg::I8 => Dtype::I8,
        }
    }
}

impl EngineArgs {
    fn options(&self) -> Options {
        Options {
            tables: !self.no_tables,
            cls_only: !self.no_cls_only,
            fused_attn: !self.no_fused_attn,
            graphs: !self.no_graphs,
            fused_bias: !self.no_fused_bias,
            fused_bias_fp32: self.fused_bias_fp32,
            chunk: self.chunk,
            recall: self.recall.map(Into::into),
            recall_tables: self.recall_tables.map(Into::into),
            profile: self.profile,
        }
    }
    fn mode(&self) -> Mode {
        match self.mode {
            ModeArg::Precision => Mode::Precision,
            ModeArg::Recall => Mode::Recall,
        }
    }
}

/// The engine, the model, the test-split input codes and the load time.
type Setup = (Box<dyn Engine>, Arc<Model>, Vec<i32>, f64);

fn setup(e: &EngineArgs) -> Result<Setup> {
    let t = Instant::now();
    let bundle = Bundle::load(&e.bundle)?;
    let model = Arc::new(Model::from_bundle(&bundle)?);
    drop(bundle);
    let load_s = t.elapsed().as_secs_f64();
    let eng = engine(e, model.clone())?;
    let nf = model.n_fields;
    let codes = read_i32(&e.bundle.join("golden/codes.i32"))?;
    let rows = read_i64(&e.bundle.join("golden/test_rows.i64"))?;
    let mut input = Vec::with_capacity(rows.len() * nf);
    for &r in &rows {
        input.extend_from_slice(&codes[r as usize * nf..(r as usize + 1) * nf]);
    }
    Ok((eng, model, input, load_s))
}

#[derive(Clone, Copy, ValueEnum)]
enum EngineKind {
    Cpu,
    Gpu,
}

#[derive(Clone, Copy, ValueEnum)]
enum ModeArg {
    Precision,
    Recall,
}

fn read_i32(p: &Path) -> Result<Vec<i32>> {
    Ok(std::fs::read(p)
        .with_context(|| p.display().to_string())?
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| i32::from_le_bytes(*c))
        .collect())
}

fn read_f32(p: &Path) -> Result<Vec<f32>> {
    Ok(std::fs::read(p)
        .with_context(|| p.display().to_string())?
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect())
}

fn read_i64(p: &Path) -> Result<Vec<i64>> {
    Ok(std::fs::read(p)
        .with_context(|| p.display().to_string())?
        .as_chunks::<8>()
        .0
        .iter()
        .map(|c| i64::from_le_bytes(*c))
        .collect())
}

fn encode_check(dir: &Path) -> Result<()> {
    let bundle = Bundle::load(dir)?;
    let enc = Encoder::new(&bundle.spec)?;
    let nf = enc.n_fields();
    let want = read_i32(&dir.join("golden/codes.i32"))?;
    let t = Instant::now();
    let lines: Vec<String> =
        BufReader::new(std::fs::File::open(dir.join("golden/profiles.jsonl"))?)
            .lines()
            .collect::<std::io::Result<_>>()?;
    let read_s = t.elapsed().as_secs_f64();
    if lines.len() * nf != want.len() {
        bail!(
            "{} profiles but {} expected code rows",
            lines.len(),
            want.len() / nf
        );
    }
    let t = Instant::now();
    let got: Vec<Vec<i32>> = lines
        .par_iter()
        .map(|line| {
            let p: Profile = serde_json::from_str(line).expect("golden profile is valid JSON");
            let mut c = vec![0; nf];
            enc.encode(&p, &mut c);
            c
        })
        .collect();
    let enc_s = t.elapsed().as_secs_f64();
    let mut bad = vec![0usize; nf];
    let mut example: Vec<Option<(usize, i32, i32)>> = vec![None; nf];
    for (r, c) in got.iter().enumerate() {
        for f in 0..nf {
            let w = want[r * nf + f];
            if c[f] != w {
                bad[f] += 1;
                example[f].get_or_insert((r, c[f], w));
            }
        }
    }
    let total: usize = bad.iter().sum();
    println!(
        "profiles {}  fields {nf}  read {read_s:.1}s  parse+encode {enc_s:.1}s ({:.0} profiles/s on {} threads)",
        lines.len(),
        lines.len() as f64 / enc_s,
        rayon::current_num_threads()
    );
    for f in 0..nf {
        if bad[f] > 0 {
            let (r, g, w) = example[f].unwrap();
            println!(
                "  MISMATCH {:<28} {:>8} rows   e.g. row {r}: got {g}, want {w}",
                bundle.spec.fields[f].name, bad[f]
            );
        }
    }
    if total > 0 {
        bail!("{total} codes differ from the training codes");
    }
    println!("encoder parity: all {} codes identical", want.len());
    Ok(())
}

fn engine(e: &EngineArgs, model: Arc<Model>) -> Result<Box<dyn Engine>> {
    Ok(match e.engine {
        EngineKind::Cpu => Box::new(CpuEngine::with_options(model, e.options())),
        #[cfg(feature = "cuda")]
        EngineKind::Gpu => Box::new(devicefp_serve::gpu::GpuEngine::with_options(
            model,
            0,
            e.max_batch,
            e.options(),
        )?),
        #[cfg(not(feature = "cuda"))]
        EngineKind::Gpu => bail!("built without the cuda feature"),
    })
}

fn embed_check(e: &EngineArgs, out: Option<PathBuf>, batch: usize, repeat: usize) -> Result<()> {
    let (eng, model, input, load_s) = setup(e)?;
    let (nf, dim) = (model.n_fields, model.dim);
    let mode = e.mode();
    let reference = read_f32(&e.bundle.join("golden/test_fp32.f32"))?;
    let n = input.len() / nf;
    let mut got = vec![0f32; n * dim];
    // one warm-up batch, then time full passes
    eng.embed(
        &input[..batch.min(n) * nf],
        batch.min(n),
        mode,
        &mut got[..batch.min(n) * dim],
    )?;
    let mut times = Vec::new();
    for _ in 0..repeat.max(1) {
        let t = Instant::now();
        for (ci, o) in got.chunks_mut(batch * dim).enumerate() {
            let b = o.len() / dim;
            eng.embed(&input[ci * batch * nf..(ci * batch + b) * nf], b, mode, o)?;
        }
        times.push(t.elapsed().as_secs_f64());
    }
    times.sort_by(f64::total_cmp);
    let secs = times[times.len() / 2];
    let stages = eng.profile();
    let stage_total: f64 = stages.iter().map(|s| s.1).sum();
    let stages: Vec<_> = stages
        .iter()
        .map(|(k, v)| serde_json::json!({"stage": k, "secs": v, "share": v / stage_total}))
        .collect();

    let mut diffs: Vec<f32> = got
        .iter()
        .zip(&reference)
        .map(|(a, b)| (a - b).abs())
        .collect();
    let mut min_cos = f64::INFINITY;
    for (a, b) in got.chunks_exact(dim).zip(reference.chunks_exact(dim)) {
        let dot: f64 = a
            .iter()
            .zip(b)
            .map(|(x, y)| (*x as f64) * (*y as f64))
            .sum();
        let na: f64 = a.iter().map(|x| (*x as f64).powi(2)).sum::<f64>().sqrt();
        let nb: f64 = b.iter().map(|x| (*x as f64).powi(2)).sum::<f64>().sqrt();
        min_cos = min_cos.min(dot / (na * nb));
    }
    diffs.sort_by(f32::total_cmp);
    let q = |p: f64| diffs[((diffs.len() - 1) as f64 * p) as usize];
    if e.json {
        println!(
            "{}",
            serde_json::json!({
                "label": e.label, "engine": eng.name(), "mode": format!("{mode:?}").to_lowercase(),
                "batch": batch, "profiles": n, "secs": secs, "profiles_per_s": n as f64 / secs,
                "max_abs_diff": q(1.0), "p999_abs_diff": q(0.999), "p50_abs_diff": q(0.5),
                "min_cosine": min_cos, "stages": stages,
            })
        );
    } else {
        println!(
            "engine {}  mode {mode:?}  model load {load_s:.1}s",
            eng.name()
        );
        println!(
            "profiles {n}  batch {batch}  {secs:.2}s  {:.0} profiles/s",
            n as f64 / secs
        );
        println!(
            "vs PyTorch fp32: max |d| {:.3e}  p99.9 {:.3e}  p50 {:.3e}  min cosine {:.9}",
            q(1.0),
            q(0.999),
            q(0.5),
            min_cos
        );
        for s in &stages {
            println!(
                "  {:<24} {:>5.1}%",
                s["stage"].as_str().unwrap_or(""),
                s["share"].as_f64().unwrap_or(0.0) * 100.0
            );
        }
    }
    if let Some(path) = out {
        let bytes: Vec<u8> = got.iter().flat_map(|v| v.to_le_bytes()).collect();
        std::fs::write(&path, bytes)?;
        if !e.json {
            println!("wrote {}", path.display());
        }
    }
    Ok(())
}

/// Per batch size: repeated engine calls on consecutive test profiles for about `secs` seconds;
/// latency percentiles per call and profiles per second.
fn sweep(e: &EngineArgs, batches: &[usize], secs: f64) -> Result<()> {
    let (eng, model, input, _) = setup(e)?;
    let (nf, dim) = (model.n_fields, model.dim);
    let mode = e.mode();
    let n = input.len() / nf;
    for &b in batches {
        let mut out = vec![0f32; b * dim];
        let mut lat = Vec::new();
        let mut start = 0;
        let t0 = Instant::now();
        let mut i = 0;
        // 3 warm-up calls, then at least 3 timed ones even when one call outlasts `secs`
        while i < 6 || t0.elapsed().as_secs_f64() < secs {
            if start + b > n {
                start = 0;
            }
            let t = Instant::now();
            eng.embed(&input[start * nf..(start + b) * nf], b, mode, &mut out)?;
            // the first calls warm up (GPU graph capture, thread pools, caches)
            if i >= 3 {
                lat.push(t.elapsed().as_secs_f64());
            }
            start += b;
            i += 1;
        }
        let total: f64 = lat.iter().sum();
        lat.sort_by(f64::total_cmp);
        let pct = |p: f64| lat[((lat.len() - 1) as f64 * p) as usize] * 1e3;
        let tput = (lat.len() * b) as f64 / total;
        if e.json {
            println!(
                "{}",
                serde_json::json!({
                    "label": e.label, "engine": eng.name(), "mode": format!("{mode:?}").to_lowercase(),
                    "batch": b, "calls": lat.len(), "p50_ms": pct(0.5), "p99_ms": pct(0.99),
                    "profiles_per_s": tput,
                })
            );
        } else {
            println!(
                "batch {b:>5}  calls {:>7}  p50 {:>8.3} ms  p99 {:>8.3} ms  {tput:>9.0} profiles/s",
                lat.len(),
                pct(0.5),
                pct(0.99)
            );
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    match Cli::parse().cmd {
        Cmd::Encode { bundle } => encode_check(&bundle),
        Cmd::Embed {
            e,
            out,
            batch,
            repeat,
        } => embed_check(&e, out, batch, repeat),
        Cmd::Sweep { e, batches, secs } => sweep(&e, &batches, secs),
    }
}

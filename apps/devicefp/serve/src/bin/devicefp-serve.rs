//! The embedding service.
//!
//!     devicefp-serve --bundle data/devicefp/serve/v3/factor_tmxweb_s1 --engine gpu --addr 0.0.0.0:8080

use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::Result;
use clap::{Parser, ValueEnum};
use devicefp_serve::bundle::Bundle;
use devicefp_serve::cpu::CpuEngine;
use devicefp_serve::encoder::Encoder;
use devicefp_serve::model::Model;
use devicefp_serve::service::{Config, router};
use devicefp_serve::{Engine, Mode};

#[derive(Parser)]
struct Args {
    /// bundle directory written by `python -m devicefp.export`
    #[arg(long)]
    bundle: PathBuf,
    #[arg(long, value_enum, default_value = "cpu")]
    engine: EngineKind,
    #[arg(long, default_value = "0.0.0.0:8080")]
    addr: String,
    /// most profiles per engine call
    #[arg(long, default_value_t = 1024)]
    max_batch: usize,
    /// extra time the batcher may wait to fill a batch (microseconds; 0 = only take what is queued)
    #[arg(long, default_value_t = 0)]
    max_wait_us: u64,
    #[arg(long, default_value_t = 4096)]
    max_request: usize,
    #[arg(long, default_value_t = 65536)]
    queue: usize,
    /// GPU ordinal
    #[arg(long, default_value_t = 0)]
    device: usize,
}

#[derive(Clone, Copy, ValueEnum)]
enum EngineKind {
    Cpu,
    Gpu,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let t = Instant::now();
    let bundle = Bundle::load(&args.bundle)?;
    let encoder = Encoder::new(&bundle.spec)?;
    let model = Arc::new(Model::from_bundle(&bundle)?);
    let name = model.name.clone();
    drop(bundle);
    let engine: Arc<dyn Engine> = match args.engine {
        EngineKind::Cpu => Arc::new(CpuEngine::new(model)),
        #[cfg(feature = "cuda")]
        EngineKind::Gpu => Arc::new(devicefp_serve::gpu::GpuEngine::with_max_batch(
            model,
            args.device,
            args.max_batch.next_power_of_two(),
        )?),
        #[cfg(not(feature = "cuda"))]
        EngineKind::Gpu => anyhow::bail!("built without the cuda feature"),
    };
    // warm up both modes (on the GPU this also captures the common batch-size graphs)
    let nf = engine.n_fields();
    for mode in [Mode::Precision, Mode::Recall] {
        let mut b = 1;
        while b <= args.max_batch {
            let mut out = vec![0f32; b * engine.dim()];
            engine.embed(&vec![0; b * nf], b, mode, &mut out)?;
            b *= 2;
        }
    }
    eprintln!(
        "{name} on {} ready in {:.1}s, listening on {}",
        engine.name(),
        t.elapsed().as_secs_f64(),
        args.addr
    );
    let cfg = Config {
        max_batch: args.max_batch,
        max_wait: Duration::from_micros(args.max_wait_us),
        max_request: args.max_request,
        queue: args.queue,
    };
    let app = router(encoder, engine, name, cfg);
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(async {
            let listener = tokio::net::TcpListener::bind(&args.addr).await?;
            axum::serve(listener, app).await?;
            Ok(())
        })
}

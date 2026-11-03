//! Load generator for devicefp-serve: keep-alive HTTP/1.1 connections sending real profiles.
//!
//!     devicefp-load --profiles golden/profiles.jsonl --concurrency 64 --seconds 20            (max throughput)
//!     devicefp-load --profiles golden/profiles.jsonl --concurrency 64 --rate 10000 --mode recall
//!
//! With --rate the connections are paced to that total request rate (open loop); latency is
//! measured from the scheduled send time, so a server that falls behind shows it.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use clap::Parser;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

#[derive(Parser)]
struct Args {
    #[arg(long, default_value = "127.0.0.1:8080")]
    addr: String,
    #[arg(long)]
    profiles: PathBuf,
    /// distinct profiles to cycle through
    #[arg(long, default_value_t = 20000)]
    sample: usize,
    /// take every k-th line of the profiles file, to spread the sample over it
    #[arg(long, default_value_t = 40)]
    stride: usize,
    /// profiles per request
    #[arg(long, default_value_t = 1)]
    batch: usize,
    #[arg(long, default_value = "precision")]
    mode: String,
    #[arg(long, default_value_t = 64)]
    concurrency: usize,
    #[arg(long, default_value_t = 15.0)]
    seconds: f64,
    /// total requests per second across connections (omit for as fast as possible)
    #[arg(long)]
    rate: Option<f64>,
}

fn find(h: &[u8], pat: &[u8]) -> Option<usize> {
    h.windows(pat.len()).position(|w| w == pat)
}

async fn run_conn(
    addr: String,
    bodies: Vec<Vec<u8>>,
    start: Instant,
    end: Instant,
    interval: Option<Duration>,
    offset: Duration,
) -> Result<(Vec<u32>, usize)> {
    let mut s = TcpStream::connect(&addr)
        .await
        .with_context(|| format!("connecting to {addr}"))?;
    s.set_nodelay(true)?;
    let mut lat_us = Vec::new();
    let mut errors = 0;
    let mut buf = vec![0u8; 1 << 16];
    let mut i = 0usize;
    let mut next = start + offset;
    loop {
        let sent = match interval {
            Some(iv) => {
                let now = Instant::now();
                if next > now {
                    tokio::time::sleep_until(next.into()).await;
                }
                let t = next;
                next += iv;
                t
            }
            None => Instant::now(),
        };
        if sent >= end {
            break;
        }
        let body = &bodies[i % bodies.len()];
        i += 1;
        s.write_all(body).await?;
        // read headers, then Content-Length bytes of body
        let mut have = 0;
        let header_end = loop {
            let n = s.read(&mut buf[have..]).await?;
            if n == 0 {
                bail!("server closed the connection");
            }
            have += n;
            if let Some(p) = find(&buf[..have], b"\r\n\r\n") {
                break p + 4;
            }
            if have == buf.len() {
                buf.resize(buf.len() * 2, 0);
            }
        };
        let head = std::str::from_utf8(&buf[..header_end])?.to_ascii_lowercase();
        let len: usize = head
            .lines()
            .find_map(|l| l.strip_prefix("content-length:"))
            .context("response without content-length")?
            .trim()
            .parse()?;
        let total = header_end + len;
        if buf.len() < total {
            buf.resize(total, 0);
        }
        while have < total {
            let n = s.read(&mut buf[have..total]).await?;
            if n == 0 {
                bail!("server closed the connection mid-body");
            }
            have += n;
        }
        if !head.starts_with("http/1.1 200") {
            errors += 1;
        }
        lat_us.push(sent.elapsed().as_micros() as u32);
    }
    Ok((lat_us, errors))
}

fn main() -> Result<()> {
    let a = Args::parse();
    let reader = BufReader::new(std::fs::File::open(&a.profiles)?);
    let picked: Vec<String> = reader
        .lines()
        .step_by(a.stride.max(1))
        .take(a.sample)
        .collect::<std::io::Result<_>>()?;
    let host = a.addr.clone();
    let bodies: Vec<Vec<u8>> = picked
        .chunks(a.batch)
        .filter(|c| c.len() == a.batch)
        .map(|c| {
            let profiles: Vec<&str> = c.iter().map(|s| s.as_str()).collect();
            let json = format!("{{\"mode\":\"{}\",\"profiles\":[{}]}}", a.mode, profiles.join(","));
            format!("POST /v1/embed HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{json}", json.len()).into_bytes()
        })
        .collect();
    let per_conn = a
        .rate
        .map(|r| Duration::from_secs_f64(a.concurrency as f64 / r));
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .build()?;
    let (lat, errors, secs) = rt.block_on(async {
        let start = Instant::now() + Duration::from_millis(200);
        let end = start + Duration::from_secs_f64(a.seconds);
        let mut tasks = Vec::new();
        for c in 0..a.concurrency {
            // stagger paced connections evenly across one interval
            let offset = per_conn
                .map(|iv| iv.mul_f64(c as f64 / a.concurrency as f64))
                .unwrap_or_default();
            let mine: Vec<Vec<u8>> = bodies
                .iter()
                .skip(c)
                .step_by(a.concurrency)
                .cloned()
                .collect();
            let mine = if mine.is_empty() {
                bodies.clone()
            } else {
                mine
            };
            tasks.push(tokio::spawn(run_conn(
                a.addr.clone(),
                mine,
                start,
                end,
                per_conn,
                offset,
            )));
        }
        let mut lat = Vec::new();
        let mut errors = 0;
        for t in tasks {
            let (l, e) = t.await??;
            lat.extend(l);
            errors += e;
        }
        Ok::<_, anyhow::Error>((lat, errors, a.seconds))
    })?;
    let mut lat = lat;
    lat.sort_unstable();
    let q = |p: f64| lat[((lat.len() - 1) as f64 * p) as usize] as f64 / 1000.0;
    let n = lat.len();
    println!(
        "mode {}  batch {}  concurrency {}  target {}  ->  {:.0} req/s  {:.0} profiles/s  errors {errors}",
        a.mode,
        a.batch,
        a.concurrency,
        a.rate
            .map(|r| format!("{r:.0} req/s"))
            .unwrap_or("max".into()),
        n as f64 / secs,
        (n * a.batch) as f64 / secs
    );
    println!(
        "latency ms  p50 {:.2}  p90 {:.2}  p99 {:.2}  p99.9 {:.2}  max {:.2}",
        q(0.5),
        q(0.9),
        q(0.99),
        q(0.999),
        q(1.0)
    );
    Ok(())
}

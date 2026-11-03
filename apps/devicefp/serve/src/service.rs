//! HTTP API and dynamic batcher.
//!
//! ```text
//! POST /v1/embed   {"mode": "precision" | "recall", "profiles": [{...}, ...]}
//!                  -> {"model", "mode", "dim", "embeddings": [[f32; dim], ...]}
//! GET  /healthz    -> {"model", "engine", "dim"}
//! ```
//!
//! Handlers parse and encode on the async runtime, then queue the codes. One worker thread owns
//! the engine: it takes the first queued job, greedily adds whatever else is already waiting (up
//! to `max_batch` profiles, optionally waiting `max_wait` for more), runs one `embed` per mode and
//! replies. Under load requests pile up while a batch runs, so batches grow by themselves; at low
//! load a lone request runs immediately.

use std::sync::Arc;
use std::sync::mpsc::{Receiver, SyncSender, TrySendError, sync_channel};
use std::time::{Duration, Instant};

use axum::extract::{DefaultBodyLimit, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tokio::sync::oneshot;

use crate::encoder::{Encoder, Profile};
use crate::{Engine, Mode};

pub struct Config {
    pub max_batch: usize,
    pub max_wait: Duration,
    /// most profiles one request may carry
    pub max_request: usize,
    /// queued jobs beyond this are refused with 503
    pub queue: usize,
}

struct Job {
    codes: Vec<i32>,
    n: usize,
    mode: Mode,
    reply: oneshot::Sender<anyhow::Result<Vec<f32>>>,
}

struct AppState {
    encoder: Encoder,
    engine_name: String,
    model: String,
    dim: usize,
    n_fields: usize,
    max_request: usize,
    jobs: SyncSender<Job>,
}

#[derive(Deserialize)]
struct EmbedRequest {
    #[serde(default)]
    mode: Mode,
    profiles: Vec<Profile>,
}

#[derive(Serialize)]
struct EmbedResponse {
    model: String,
    mode: Mode,
    dim: usize,
    embeddings: Vec<Vec<f32>>,
}

fn error(status: StatusCode, msg: impl Into<String>) -> Response {
    (status, Json(serde_json::json!({ "error": msg.into() }))).into_response()
}

async fn embed(
    State(st): State<Arc<AppState>>,
    req: Result<Json<EmbedRequest>, axum::extract::rejection::JsonRejection>,
) -> Response {
    let Json(req) = match req {
        Ok(r) => r,
        Err(e) => return error(StatusCode::BAD_REQUEST, e.body_text()),
    };
    let n = req.profiles.len();
    if n == 0 || n > st.max_request {
        return error(
            StatusCode::BAD_REQUEST,
            format!("send between 1 and {} profiles per request", st.max_request),
        );
    }
    let mut codes = vec![0; n * st.n_fields];
    for (p, c) in req.profiles.iter().zip(codes.chunks_exact_mut(st.n_fields)) {
        st.encoder.encode(p, c);
    }
    let (tx, rx) = oneshot::channel();
    match st.jobs.try_send(Job {
        codes,
        n,
        mode: req.mode,
        reply: tx,
    }) {
        Ok(()) => {}
        Err(TrySendError::Full(_)) => {
            return error(StatusCode::SERVICE_UNAVAILABLE, "queue full, retry later");
        }
        Err(TrySendError::Disconnected(_)) => {
            return error(StatusCode::INTERNAL_SERVER_ERROR, "engine stopped");
        }
    }
    let flat = match rx.await {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => return error(StatusCode::INTERNAL_SERVER_ERROR, format!("{e:#}")),
        Err(_) => {
            return error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "engine dropped the request",
            );
        }
    };
    let embeddings = flat.chunks_exact(st.dim).map(<[f32]>::to_vec).collect();
    Json(EmbedResponse {
        model: st.model.clone(),
        mode: req.mode,
        dim: st.dim,
        embeddings,
    })
    .into_response()
}

async fn healthz(State(st): State<Arc<AppState>>) -> Response {
    Json(serde_json::json!({ "model": st.model, "engine": st.engine_name, "dim": st.dim }))
        .into_response()
}

/// Groups queued jobs into engine calls; runs on its own OS thread.
fn worker(engine: Arc<dyn Engine>, rx: Receiver<Job>, cfg: &Config) {
    let (nf, dim) = (engine.n_fields(), engine.dim());
    let mut pending: Vec<Job> = Vec::new();
    while let Ok(first) = rx.recv() {
        let mut total = first.n;
        pending.push(first);
        let deadline = Instant::now() + cfg.max_wait;
        while total < cfg.max_batch {
            let next = match rx.try_recv() {
                Ok(j) => Some(j),
                Err(_) => {
                    let left = deadline.saturating_duration_since(Instant::now());
                    if left.is_zero() {
                        None
                    } else {
                        rx.recv_timeout(left).ok()
                    }
                }
            };
            let Some(j) = next else { break };
            total += j.n;
            pending.push(j);
        }
        for mode in [Mode::Precision, Mode::Recall] {
            let group: Vec<Job> = {
                let (g, rest): (Vec<Job>, Vec<Job>) =
                    pending.drain(..).partition(|j| j.mode == mode);
                pending = rest;
                g
            };
            if group.is_empty() {
                continue;
            }
            let n: usize = group.iter().map(|j| j.n).sum();
            let mut codes = Vec::with_capacity(n * nf);
            for j in &group {
                codes.extend_from_slice(&j.codes);
            }
            let mut out = vec![0f32; n * dim];
            let result = engine.embed(&codes, n, mode, &mut out);
            let mut at = 0;
            for j in group {
                let r = match &result {
                    Ok(()) => Ok(out[at * dim..(at + j.n) * dim].to_vec()),
                    Err(e) => Err(anyhow::anyhow!("{e:#}")),
                };
                at += j.n;
                let _ = j.reply.send(r);
            }
        }
    }
}

pub fn router(encoder: Encoder, engine: Arc<dyn Engine>, model: String, cfg: Config) -> Router {
    let (tx, rx) = sync_channel(cfg.queue);
    let st = Arc::new(AppState {
        encoder,
        engine_name: engine.name(),
        model,
        dim: engine.dim(),
        n_fields: engine.n_fields(),
        max_request: cfg.max_request,
        jobs: tx,
    });
    std::thread::Builder::new()
        .name("devicefp-engine".into())
        .spawn(move || worker(engine, rx, &cfg))
        .expect("spawning the engine thread");
    Router::new()
        .route("/v1/embed", post(embed))
        .route("/healthz", get(healthz))
        .layer(DefaultBodyLimit::max(64 << 20))
        .with_state(st)
}

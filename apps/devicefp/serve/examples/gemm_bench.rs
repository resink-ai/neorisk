//! fp32 GEMM vs int8 GEMM (with and without activation quantisation) on the CPU engine's shapes:
//! one task's rows (2 profiles x 112 tokens of the id tower) through each linear layer.
//!
//!     cargo run --release --example gemm_bench

use std::hint::black_box;
use std::time::Instant;

use devicefp_serve::math::matmul;
use devicefp_serve::qgemm::{QLin, qgemm, quantize_rows};

fn time(mut f: impl FnMut()) -> f64 {
    for _ in 0..50 {
        f();
    }
    let mut best = f64::INFINITY;
    for _ in 0..7 {
        let t = Instant::now();
        for _ in 0..500 {
            f();
        }
        best = best.min(t.elapsed().as_secs_f64() / 500.0);
    }
    best
}

fn main() {
    let m = 224;
    println!("rows {m}, single thread; microseconds per call");
    println!(
        "{:<22} {:>8} {:>10} {:>12} {:>9}",
        "layer (k -> n)", "fp32", "int8 GEMM", "+ quantise", "speed-up"
    );
    for (name, k, n) in [
        ("out_proj 64 -> 64", 64, 64),
        ("K/V 64 -> 128", 64, 128),
        ("Q/K/V 64 -> 192", 64, 192),
        ("FFN up 64 -> 256", 64, 256),
        ("FFN down 256 -> 64", 256, 64),
    ] {
        let x: Vec<f32> = (0..m * k)
            .map(|i| ((i * 37 % 101) as f32 - 50.0) / 25.0)
            .collect();
        let w: Vec<f32> = (0..k * n)
            .map(|i| ((i * 53 % 97) as f32 - 48.0) / 60.0)
            .collect();
        let b = vec![0.1f32; n];
        let mut out = vec![0f32; m * n];
        let f32_s = time(|| {
            matmul(m, n, k, black_box(&x), k, &w, n, &mut out, n, false, 1);
        });
        let lin = QLin::new(&w, n, k, n);
        let (mut q, mut s) = (vec![0i16; m * k], vec![0f32; m]);
        quantize_rows(&x, k, m, k, &mut q, &mut s);
        let i8_s = time(|| qgemm(m, black_box(&q), &s, &lin, &b, &mut out, n, false, false));
        let full_s = time(|| {
            quantize_rows(black_box(&x), k, m, k, &mut q, &mut s);
            qgemm(m, &q, &s, &lin, &b, &mut out, n, false, false)
        });
        println!(
            "{name:<22} {:>8.2} {:>10.2} {:>12.2} {:>8.2}x",
            f32_s * 1e6,
            i8_s * 1e6,
            full_s * 1e6,
            f32_s / full_s
        );
    }
}

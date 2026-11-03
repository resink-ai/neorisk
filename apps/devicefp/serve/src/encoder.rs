//! Raw JSON profile -> per-field codes, following v3.prepare exactly.
//!
//! Categorical fields: cast to string, strip, placeholders are missing (0), vocabulary values keep
//! their code, anything else is out of vocabulary (1). Numeric fields: missing or NaN is 0, else
//! 2 + the number of bin edges <= x. Two fields are derived: `ip_geo_cell` from latitude and
//! longitude rounded like polars, and `ip_subnet24` from a regex on `privateIp`.

use std::collections::{HashMap, HashSet};

use anyhow::{Result, bail};
use regex::Regex;
use serde_json::{Map, Value};

use crate::bundle::{Derived, EncoderSpec, FieldKind};

pub type Profile = Map<String, Value>;

enum Source {
    Column(String),
    GeoCell {
        lat: String,
        lon: String,
        scale: f64,
        sep: String,
    },
    Regex {
        from: String,
        re: Regex,
    },
}

struct Field {
    kind: FieldKind,
    size: i32,
    source: Source,
    vocab: HashMap<String, i32>,
    edges: Vec<f64>,
}

pub struct Encoder {
    fields: Vec<Field>,
    placeholders: HashSet<String>,
}

impl Encoder {
    pub fn new(spec: &EncoderSpec) -> Result<Self> {
        let mut fields = Vec::with_capacity(spec.fields.len());
        for f in &spec.fields {
            let source = match &f.derived {
                None => Source::Column(f.name.clone()),
                Some(Derived::GeoCell {
                    lat,
                    lon,
                    decimals,
                    sep,
                }) => Source::GeoCell {
                    lat: lat.clone(),
                    lon: lon.clone(),
                    scale: 10f64.powi(*decimals),
                    sep: sep.clone(),
                },
                Some(Derived::Regex { from, pattern }) => Source::Regex {
                    from: from.clone(),
                    re: Regex::new(pattern)?,
                },
            };
            if f.kind == FieldKind::Num && f.edges.windows(2).any(|w| w[0] >= w[1]) {
                bail!("field {}: bin edges are not strictly increasing", f.name);
            }
            fields.push(Field {
                kind: f.kind,
                size: f.size,
                source,
                vocab: f.vocab.clone(),
                edges: f.edges.clone(),
            });
        }
        Ok(Self {
            fields,
            placeholders: spec.placeholders.iter().cloned().collect(),
        })
    }

    pub fn n_fields(&self) -> usize {
        self.fields.len()
    }

    /// Writes one code per field into `out` (length n_fields).
    pub fn encode(&self, p: &Profile, out: &mut [i32]) {
        for (f, o) in self.fields.iter().zip(out.iter_mut()) {
            *o = match &f.source {
                Source::Column(name) => match f.kind {
                    FieldKind::Cat => self.categorical(f, p.get(name).and_then(as_text).as_deref()),
                    FieldKind::Num => numeric(f, p.get(name).and_then(as_number)),
                },
                Source::GeoCell {
                    lat,
                    lon,
                    scale,
                    sep,
                } => {
                    let cell = match (
                        p.get(lat).and_then(as_number),
                        p.get(lon).and_then(as_number),
                    ) {
                        (Some(a), Some(b)) => Some(format!(
                            "{}{sep}{}",
                            polars_float(round_like_polars(a, *scale)),
                            polars_float(round_like_polars(b, *scale))
                        )),
                        _ => None,
                    };
                    self.categorical(f, cell.as_deref())
                }
                Source::Regex { from, re } => {
                    let v = p
                        .get(from)
                        .and_then(Value::as_str)
                        .and_then(|s| re.captures(s))
                        .and_then(|c| c.get(1))
                        .map(|m| m.as_str());
                    self.categorical(f, v)
                }
            };
        }
    }

    fn categorical(&self, f: &Field, v: Option<&str>) -> i32 {
        let Some(v) = v else { return 0 };
        let v = v.trim();
        if v.is_empty() || self.placeholders.contains(v) {
            return 0;
        }
        f.vocab.get(v).copied().unwrap_or(1)
    }
}

fn numeric(f: &Field, x: Option<f64>) -> i32 {
    match x {
        Some(x) if !x.is_nan() => (2 + f.edges.partition_point(|e| *e <= x) as i32).min(f.size - 1),
        _ => 0,
    }
}

/// A categorical value as polars would cast it to a string.
fn as_text(v: &Value) -> Option<std::borrow::Cow<'_, str>> {
    match v {
        Value::String(s) => Some(s.as_str().into()),
        Value::Bool(b) => Some(if *b { "true" } else { "false" }.into()),
        Value::Number(n) => Some(n.to_string().into()),
        _ => None,
    }
}

fn as_number(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

/// polars `Expr.round(decimals)` on floats: scale, round half to even, unscale.
fn round_like_polars(x: f64, scale: f64) -> f64 {
    (x * scale).round_ties_even() / scale
}

/// polars float -> string: shortest round-trip digits, always with a decimal point.
fn polars_float(x: f64) -> String {
    let s = format!("{x}");
    if s.contains(['.', 'e', 'E', 'N', 'i']) {
        s
    } else {
        s + ".0"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encoder() -> Encoder {
        let spec: EncoderSpec = serde_json::from_value(serde_json::json!({
            "model": "test", "placeholders": ["", "unknown"], "layer_norm_eps": 1e-5, "dim": 0, "towers": [],
            "fields": [
                {"name": "os", "size": 4, "raw": "string", "kind": "cat", "vocab": {"iOS": 2, "Android": 3}},
                {"name": "jb", "size": 4, "raw": "bool", "kind": "cat", "vocab": {"false": 2, "true": 3}},
                {"name": "w", "size": 6, "raw": "int", "kind": "num", "edges": [100.0, 200.0, 300.0]},
                {"name": "cell", "size": 3, "raw": "string", "kind": "cat", "vocab": {"31.6|74.3": 2},
                 "derived": {"kind": "geo_cell", "lat": "lat", "lon": "lon", "decimals": 1, "sep": "|"}},
                {"name": "net", "size": 3, "raw": "string", "kind": "cat", "vocab": {"192.168.0": 2},
                 "derived": {"kind": "regex", "from": "ip", "pattern": "^(\\d+\\.\\d+\\.\\d+)\\.\\d+$"}}
            ]
        }))
        .unwrap();
        Encoder::new(&spec).unwrap()
    }

    fn codes(p: serde_json::Value) -> Vec<i32> {
        let e = encoder();
        let mut out = vec![-1; e.n_fields()];
        e.encode(p.as_object().unwrap(), &mut out);
        out
    }

    #[test]
    fn categorical_cleaning_and_oov() {
        assert_eq!(
            codes(serde_json::json!({"os": " iOS "}))[0],
            2,
            "stripped before lookup"
        );
        assert_eq!(
            codes(serde_json::json!({"os": "unknown"}))[0],
            0,
            "placeholder is missing"
        );
        assert_eq!(
            codes(serde_json::json!({"os": "   "}))[0],
            0,
            "blank is missing"
        );
        assert_eq!(
            codes(serde_json::json!({"os": "Tizen"}))[0],
            1,
            "unseen value is out of vocabulary"
        );
        assert_eq!(codes(serde_json::json!({"os": null}))[0], 0);
        assert_eq!(codes(serde_json::json!({}))[0], 0, "absent key is missing");
        assert_eq!(
            codes(serde_json::json!({"jb": true}))[1],
            3,
            "bool encodes as polars' string"
        );
    }

    #[test]
    fn numeric_bins() {
        // code = 2 + #{edges <= x}; missing, null and NaN-like inputs are 0
        let w = |v| codes(serde_json::json!({ "w": v }))[2];
        assert_eq!(w(serde_json::json!(50)), 2);
        assert_eq!(
            w(serde_json::json!(100)),
            3,
            "an edge belongs to the bin above (searchsorted right)"
        );
        assert_eq!(w(serde_json::json!(250.5)), 4);
        assert_eq!(w(serde_json::json!(1e9)), 5);
        assert_eq!(w(serde_json::json!("150")), 3, "numeric strings are parsed");
        assert_eq!(w(serde_json::json!("n/a")), 0);
        assert_eq!(w(serde_json::Value::Null), 0);
    }

    #[test]
    fn derived_fields() {
        let c = codes(serde_json::json!({"lat": 31.5826, "lon": 74.3276, "ip": "192.168.0.105"}));
        assert_eq!((c[3], c[4]), (2, 2));
        let c = codes(serde_json::json!({"lat": 31.5826, "ip": "2a00:1370::1"}));
        assert_eq!(
            (c[3], c[4]),
            (0, 0),
            "a missing coordinate or a non-IPv4 address is missing"
        );
        assert_eq!(
            codes(serde_json::json!({"lat": 1.0, "lon": 2.0}))[3],
            1,
            "unseen cell is out of vocabulary"
        );
    }

    #[test]
    fn rounds_like_polars() {
        // values checked against polars 1.x: pl.col("x").round(1).cast(pl.String)
        let cases = [
            (-0.04, "-0.0"),
            (0.05, "0.0"),
            (0.15, "0.2"),
            (0.25, "0.2"),
            (2.675, "2.7"),
            (-122.0, "-122.0"),
            (30.0, "30.0"),
            (1.45, "1.4"),
        ];
        for (x, want) in cases {
            assert_eq!(polars_float(round_like_polars(x, 10.0)), want, "x = {x}");
        }
    }
}

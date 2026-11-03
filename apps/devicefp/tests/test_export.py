import json
import struct

import numpy as np
import polars as pl
import torch

from devicefp import v3
from devicefp.export import categorical_vocab, derive, numeric_edges, write_safetensors
from devicefp.v2 import _clean


def test_categorical_vocab_reproduces_v3_codes():
    values = ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["rare"] * 2 + [None, " a ", "unknown"]
    s = _clean(pl.Series(values))
    vocab, codes = categorical_vocab(s, cap=4)
    want, _ = v3._encode_capped(s, 4)
    assert np.array_equal(codes, want)
    # cap 4 keeps the 2 most frequent values; rare and capped-out values are OOV (1), missing is 0
    assert vocab == {"a": 2, "b": 3}
    assert [vocab.get(v, 1) if v is not None else 0 for v in s.to_list()] == codes.tolist()


def test_numeric_edges_reproduce_v3_bins():
    rng = np.random.default_rng(0)
    x = pl.Series(np.concatenate([rng.normal(size=500), [np.nan] * 5]))
    edges, codes = numeric_edges(x, bins=8)
    want, _ = v3._encode_binned(x, 8)
    assert np.array_equal(codes, want)
    vals = x.to_numpy()
    rule = np.where(np.isnan(vals), 0, 2 + np.searchsorted(np.array(edges), vals, side="right"))
    assert np.array_equal(rule, codes)


def test_derive_matches_prepare_rules():
    df = derive(pl.DataFrame({"ip_latitude": [31.5826, 0.25, None], "ip_longitude": [74.3276, -122.0, 1.0],
                              "privateIp": ["192.168.0.105", "fe80::1", "10.0.0.7"]}))
    assert df["ip_geo_cell"].to_list() == ["31.6|74.3", "0.2|-122.0", None]
    assert df["ip_subnet24"].to_list() == ["192.168.0", None, "10.0.0"]


def test_safetensors_round_trip(tmp_path):
    t = {"a.weight": torch.arange(6, dtype=torch.float32).reshape(2, 3), "b": torch.tensor([1.5])}
    path = tmp_path / "m.safetensors"
    write_safetensors(path, t)
    raw = path.read_bytes()
    n = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8 + n])
    assert n % 8 == 0
    for name, tensor in t.items():
        h = header[name]
        assert h["dtype"] == "F32" and h["shape"] == list(tensor.shape)
        lo, hi = h["data_offsets"]
        got = np.frombuffer(raw[8 + n + lo:8 + n + hi], dtype="<f4").reshape(h["shape"])
        assert np.array_equal(got, tensor.numpy())

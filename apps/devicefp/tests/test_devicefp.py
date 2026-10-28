from datetime import datetime

import numpy as np
import polars as pl
import pytest
import torch

from devicefp import evaluate as ev
from devicefp.features import BUCKETS, MASK, Drift, augment, bucket, encode
from devicefp.ingest import parse_dump
from devicefp.model import Config, embed, train
from devicefp.profiles import Field, Profiles, fonts, from_fpstalker, plugins, ua_words
from devicefp.synth import bump, consistent, generate

torch.set_num_threads(1)


def test_parse_dump_handles_escapes_null_and_numbers():
    text = ("INSERT INTO `extensionDataScheme` (`counter`, `id`, `canvasJS`, `x`) VALUES\n"
            "(1, 'a\\'b', 'img', NULL),\n(2, 'c,d (e)', 'img', 'tab\\there');\n")
    df = parse_dump(text)
    assert df.columns == ["counter", "id", "x"]            # canvasJS is dropped
    assert df.rows() == [("1", "a'b", None), ("2", "c,d (e)", "tab\there")]


def test_field_parsers():
    assert plugins("Plugin 0: Flash; desc; f.dll. Plugin 1: PDF; d; p.") == ["Flash", "PDF"]
    assert fonts("Arial_Verdana") == ["Arial", "Verdana"]
    assert fonts("Flash not detected") == []
    assert "Firefox/41.0" in ua_words("Mozilla/5.0 (Windows NT 6.1) Firefox/41.0")


def _raw(n_dev=6, per=3):
    rows = []
    for d in range(n_dev):
        for k in range(per):
            rows.append({"counter": len(rows), "id": f"d{d}",
                         "creationDate": datetime(2016, 1, 1 + k * 3 + d % 2),
                         "addressHttp": f"ip{d}-{k % 2}", "userAgentHttp": f"UA/{d} v/{k}",
                         "pluginsJS": f"Plugin 0: P{d}; x; y.", "fontsFlash": f"F{d}_G",
                         "languageHttp": "en-US,en;q=0.5"})
    df = pl.DataFrame(rows)
    from devicefp.profiles import FPSTALKER_CAT
    for src in FPSTALKER_CAT:
        if src not in df.columns:
            df = df.with_columns(pl.lit("v").alias(src))
    return df


def _profiles():
    return from_fpstalker(_raw(), consistent={f"d{d}" for d in range(5)})


def test_from_fpstalker_groups_and_fields():
    p = _profiles()
    assert set(p.table["group"]) == {"consistent", "spoofer"}
    assert p.table["seen_at"].is_sorted()
    assert {f.name for f in p.fields if f.kind == "set"} == {"plugins", "fonts", "ua_words",
                                                             "languages"}


def test_encode_and_augment_keep_one_array_per_field():
    p = _profiles()
    enc = encode(p)
    assert len(enc) == len(p) and all(len(r) == len(p.fields) for r in enc.rows)
    assert all(0 < t < BUCKETS for r in enc.rows for a in r for t in a)
    assert bucket("f", "v") == bucket("f", "v") != bucket("g", "v")
    rng = np.random.default_rng(0)
    out = augment(enc.rows[0], enc, rng, Drift(swap=0, mask=1.0))
    assert all(list(a) == [MASK] for a in out)
    assert augment(enc.rows[0], enc, rng, Drift(0, 0, 0, 0))[0] is enc.rows[0][0]


def test_split_folds_partition_devices():
    p = _profiles()
    tests = [k for f in range(5) for k, v in ev.split_devices(p, fold=f).items() if v == "test"]
    assert sorted(tests) == sorted(set(tests)) == [f"d{d}" for d in range(5)]


def test_protocols_on_a_perfect_scorer():
    devices = np.array(["a", "b", "a", "b", "c"])
    pos = np.array([0.0, 10.0, 0.1, 10.1, 50.0])
    dist = lambda q, g: np.abs(pos[q][:, None] - pos[g][None, :])
    rows = np.arange(5)
    t = ev.track(dist, devices, rows)
    assert t.filter(pl.col("returning"))["rank"].to_list() == [1, 1]
    assert ev.open_set(t, threshold=1.0)["open_set_acc"] == 1.0
    days = np.arange(5, dtype=float)
    assert ev.enroll_metrics(ev.enroll(dist, devices, days, rows))["top1"] == 1.0
    v = ev.verify(dist, devices, rows)
    assert v["roc_auc"] == 1.0 and v["eer"] == 0.0


def test_naive_bayes_rewards_rare_matches_more():
    c = np.array([[0, 0], [0, 0], [0, 1], [0, 2], [0, 3], [0, 3]])
    devices = np.array(["a", "a", "b", "c", "d", "d"])
    nb = ev.NaiveBayes.fit(c, devices, np.arange(6))
    assert nb.match[1] > nb.match[0]          # field 1 is diverse, field 0 is constant


def test_train_embeds_on_the_unit_sphere_and_links_identical_profiles():
    p = _profiles()
    enc = encode(p)
    cfg = Config(epochs=2, devices_per_batch=4, width=16, dim=8, code_dim=4, heads=2,
                 layers=1)
    model, hist = train(enc, p.table["device"].to_numpy(), cfg, torch.device("cpu"),
                        log=lambda s: None)
    z = embed(model, enc, torch.device("cpu"))
    assert z.shape == (len(p), 8 + 4 * len(p.fields)) and len(hist) == 2
    assert np.allclose(np.linalg.norm(z, axis=1), 1, atol=1e-5)
    twice = embed(model, type(enc)([enc.rows[0], enc.rows[0]], enc.fields),
                  torch.device("cpu"))
    assert np.allclose(twice[0], twice[1], atol=1e-6)


def test_synth_is_deterministic_and_bumps_versions():
    assert bump("Mozilla/5.0 Chrome/120.0 Safari/537", 2) == "Mozilla/5.0 Chrome/122.0 Safari/537"
    assert not consistent("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7)", "Linux x86_64",
                          "mobile", "375x812")
    base = pl.DataFrame({"user_agent": ["Mozilla/5.0 (iPhone) Version/18.0"],
                         "platform": ["iPhone"], "vendor": ["Apple"], "category": ["mobile"],
                         "screen": ["390x844"], "viewport": ["390x700"], "language": ["en"],
                         "plugins_length": [0], "effective_type": ["4g"], "weight": [1.0]})
    a, b = generate(base, devices=20, seed=1), generate(base, devices=20, seed=1)
    assert a.table.equals(b.table)
    assert a.table["device"].n_unique() == 20
    assert isinstance(a.fields[0], Field) and isinstance(a, Profiles)


@pytest.mark.parametrize("fold", [0, 1])
def test_split_has_no_overlap(fold):
    s = ev.split_devices(_profiles(), fold=fold)
    assert set(s.values()) <= {"train", "val", "test"}

import json
import re

import pytest

from bench.cli import main as bench_main
from bench.compare import run_compare, write_outputs
from datagen.cli import main as datagen_main


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("cmp")
    datagen_main(
        [
            "generate",
            "--scenario",
            "fraud",
            "--n-events",
            "20000",
            "--seed",
            "21",
            "--span-days",
            "60",
            "--out",
            str(out),
        ]
    )
    return out


def test_run_compare_all_models(data_dir):
    r = run_compare(data_dir, shap_rows=400, ann_shap_rows=40, seed=0)
    assert set(r["models"]) == {"logreg", "rf", "xgb", "ann_small", "ann_large"}
    for name, m in r["models"].items():
        assert m["failed"] is None, (name, m["failed"])
        assert m["metrics"]["auc"] > 0.5
        assert m["shap"] and m["shap"]["importance"]
    assert r["run"]["n_events"] == 20000 and r["run"]["n_features"] > 10
    assert sum(r["run"]["split_sizes"].values()) == 20000
    assert r["models"]["ann_small"]["epochs"] >= 1 and r["models"]["xgb"]["epochs"] is None
    t = r["run"]["timings"]
    assert t["feature_seconds"] >= 0 and t["total_seconds"] >= t["feature_seconds"]
    assert all(m["shap_seconds"] >= 0 for m in r["models"].values())


def test_golden_parquet_is_never_read(data_dir, monkeypatch):
    import polars as pl

    real = pl.read_parquet

    def guard(path, *a, **k):
        assert "golden" not in str(path)
        return real(path, *a, **k)

    monkeypatch.setattr(pl, "read_parquet", guard)
    run_compare(data_dir, models=("logreg",), shap_rows=200, seed=0)


def test_failed_model_does_not_kill_run(data_dir, monkeypatch):
    import bench.models as m

    monkeypatch.setitem(
        m._FACTORIES, "rf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    r = run_compare(data_dir, models=("logreg", "rf"), shap_rows=200, seed=0)
    assert r["models"]["rf"]["failed"] and r["models"]["logreg"]["failed"] is None


def test_cli_writes_report_and_json(data_dir, tmp_path):
    html, js = tmp_path / "r.html", tmp_path / "m.json"
    rc = bench_main(
        [
            "compare",
            str(data_dir),
            "--out",
            str(html),
            "--json",
            str(js),
            "--models",
            "logreg,xgb",
            "--shap-rows",
            "300",
            "--lang",
            "en",
        ]
    )
    assert rc == 0 and html.exists() and js.exists()
    page = html.read_text()
    assert "Logistic Regression" in page and "XGBoost" in page
    assert "Stage seconds" in page and "SHAP s" in page  # per-stage timings rendered
    assert not re.search(r"(src|href)=[\"']https?://", page)
    data = json.loads(js.read_text())  # strict JSON: no NaN literals
    assert data["models"]["xgb"]["metrics"]["auc"] > 0.5


def test_cli_rejects_unknown_model(data_dir, tmp_path):
    with pytest.raises(SystemExit):
        bench_main(["compare", str(data_dir), "--out", str(tmp_path / "r.html"), "--models", "svm"])


def test_single_class_labels_still_render(data_dir, tmp_path):
    import polars as pl

    d = tmp_path / "flat"
    d.mkdir()
    ev = pl.read_parquet(data_dir / "events.parquet").with_columns(label=pl.lit(0))
    ev.write_parquet(d / "events.parquet")
    (d / "meta.json").write_text((data_dir / "meta.json").read_text())
    r = run_compare(d, models=("logreg",), shap_rows=100, seed=0)
    assert r["models"]["logreg"]["failed"]
    write_outputs(r, tmp_path / "x.html", tmp_path / "x.json", lang="en")
    assert (tmp_path / "x.html").exists()
    json.loads((tmp_path / "x.json").read_text())

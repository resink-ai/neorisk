import json
import re

import polars as pl
import pytest

from bench.cli import main as bench_main
from bench.compare import run_compare, write_outputs

pytest_plugins = ["legacy_fixture"]


@pytest.mark.large
def test_run_compare_all_models(legacy_dir):
    r = run_compare(legacy_dir, shap_rows=400, ann_shap_rows=40, seed=0)
    assert set(r["models"]) == {"logreg", "rf", "xgb", "ann_small", "ann_large"}
    for name, m in r["models"].items():
        assert m["failed"] is None, (name, m["failed"])
        assert 0 <= m["metrics"]["auc"] <= 1
        assert m["shap"] and m["shap"]["importance"]
    # every model beat chance on the old 20k-row data; on the ~3.5k-row legacy export the ANNs
    # get 2-3 mini-batches per epoch and their test AUC is seed noise (0.48-0.66), so only the
    # models that converge on it are held to it
    for name in ("logreg", "rf", "xgb"):
        assert r["models"][name]["metrics"]["auc"] > 0.5, name
    n = pl.read_parquet(legacy_dir / "events.parquet").height
    assert r["run"]["n_events"] == n and r["run"]["n_features"] > 10
    assert sum(r["run"]["split_sizes"].values()) == n
    assert r["models"]["ann_small"]["epochs"] >= 1
    assert 1 <= r["models"]["xgb"]["epochs"] <= 1000  # best_iteration + 1 (rounds kept)
    for name, m in r["models"].items():
        info = m["model_info"]
        assert info["imbalance"] and info["shap_unit"] in ("log-odds", "probability")
        assert info["weighted"] == (name in ("logreg", "rf"))
        assert info["epochs"] == m["epochs"]
        assert m["shap"]["unit"] == info["shap_unit"]
        assert 0 < m["mean_pred"] < 1
    assert r["models"]["xgb"]["model_info"]["count_unit"] == "rounds"
    assert r["run"]["train_positives"] > 0 and r["run"]["shap_sample_pos_rate"] > 0
    t = r["run"]["timings"]
    assert t["feature_seconds"] >= 0 and t["total_seconds"] >= t["feature_seconds"]
    assert all(m["shap_seconds"] >= 0 for m in r["models"].values())


@pytest.mark.large
def test_golden_parquet_is_never_read(legacy_dir, monkeypatch):
    real = pl.read_parquet

    def guard(path, *a, **k):
        assert "golden" not in str(path)
        return real(path, *a, **k)

    monkeypatch.setattr(pl, "read_parquet", guard)
    run_compare(legacy_dir, models=("logreg",), shap_rows=200, seed=0)


@pytest.mark.large
def test_failed_model_does_not_kill_run(legacy_dir, monkeypatch):
    import bench.models as m

    monkeypatch.setitem(
        m._FACTORIES, "rf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    r = run_compare(legacy_dir, models=("logreg", "rf"), shap_rows=200, seed=0)
    assert r["models"]["rf"]["failed"] and r["models"]["logreg"]["failed"] is None


@pytest.mark.large
def test_cli_writes_report_and_json(legacy_dir, tmp_path):
    html, js = tmp_path / "r.html", tmp_path / "m.json"
    rc = bench_main(
        [
            "compare",
            str(legacy_dir),
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
    assert "Methods &amp; caveats" in page and "TreeExplainer · log-odds" in page
    assert "Predict test s" in page and "Rounds/epochs" in page
    assert not re.search(r"(src|href)=[\"']https?://", page)
    data = json.loads(js.read_text())  # strict JSON: no NaN literals
    assert data["models"]["xgb"]["metrics"]["auc"] > 0.5


@pytest.mark.large
def test_cli_rejects_unknown_model(legacy_dir, tmp_path):
    with pytest.raises(SystemExit):
        bench_main(["compare", str(legacy_dir), "--out", str(tmp_path / "r.html"),
                    "--models", "svm"])


@pytest.mark.large
def test_single_class_labels_still_render(legacy_dir, tmp_path):
    d = tmp_path / "flat"
    d.mkdir()
    ev = pl.read_parquet(legacy_dir / "events.parquet").with_columns(label=pl.lit(0))
    ev.write_parquet(d / "events.parquet")
    (d / "meta.json").write_text((legacy_dir / "meta.json").read_text())
    r = run_compare(d, models=("logreg",), shap_rows=100, seed=0)
    assert r["models"]["logreg"]["failed"]
    write_outputs(r, tmp_path / "x.html", tmp_path / "x.json", lang="en")
    assert (tmp_path / "x.html").exists()
    json.loads((tmp_path / "x.json").read_text())

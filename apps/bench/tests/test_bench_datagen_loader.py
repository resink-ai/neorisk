"""bench reads any datagen dataset with label maturity: late labels are not used for training."""

import shutil
from pathlib import Path

import polars as pl
import pytest

from bench.datagen_loader import features, load_rows, maturity_split

PAY = Path(__file__).resolve().parents[3] / "examples" / "payments"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    from datagen.cli import main
    proj = tmp_path_factory.mktemp("pay") / "payments"
    shutil.copytree(PAY, proj, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(proj), "--set", "customers=500", "--set", "run.days=90",
                 "--set", "fraud_p=0.03"]) == 0
    return proj / "out" / "default-s7"


def test_rows_carry_final_labels_and_their_availability(run_dir):
    rows = load_rows(run_dir, "payment_authorized", "payment_id", roles=["fraud"])
    pos = rows.filter(pl.col("label") == 1)
    assert pos.height > 20 and rows["label"].mean() < 0.1
    assert (pos["label_available_at"] > pos["event_time"]).all()       # labels arrive late
    assert "amount" in features(rows) and "payment_id" not in features(rows)


def test_maturity_split_hides_labels_that_arrive_after_the_cutoff(run_dir):
    rows = load_rows(run_dir, "payment_authorized", "payment_id", roles=["fraud"])
    train, test = maturity_split(rows, cutoff_day=60, test_days=14)
    assert train.height and test.height
    assert train["event_time"].max() < test["event_time"].min()
    final, observed = train["label"].sum(), train["label_obs"].sum()
    assert observed < final                                  # some fraud is not yet known
    last2w = train.filter(pl.col("event_time") >= train["event_time"].max() - pl.duration(days=14))
    assert last2w["label_obs"].sum() < last2w["label"].sum() * 0.5   # recent: mostly immature


def test_bench_datagen_command(run_dir, capsys):
    import json

    from bench.cli import main
    assert main(["datagen", str(run_dir), "--event", "payment_authorized", "--key",
                 "payment_id", "--role", "fraud", "--cutoff-day", "60"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["train_positives_known_at_cutoff"] < res["train_positives_final"]
    assert {"auc", "pr_auc"} <= set(res["known_at_cutoff"])

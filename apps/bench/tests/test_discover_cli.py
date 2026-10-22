"""`bench discover` end to end: a run (given or generated) in, JSON and a report out."""

import json
import re
from pathlib import Path

from bench.cli import main

pytest_plugins = ["discover_fixture"]
ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


def _check_outputs(out: Path, methods):
    res = json.loads((out / "discover.json").read_text())
    assert list(res["methods"]) == methods
    assert set(res["methods"]["rules"]["by_budget"]) == {"0", "1", "2"}
    page = (out / "discover.html").read_text()
    assert "<svg" in page and "{{" not in page
    assert not re.search(r"<(script|link|img)[^>]+(src|href)=", page)
    return res


def test_discover_on_an_existing_run(discover_run, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["discover", "--run", str(discover_run), "--methods", "random,rules",
                 "--k", "3", "--rounds", "2", "--sweep", "0,1", "--seed-draws", "1",
                 "--report-day", "40", "--out", str(out), "--lang", "en"]) == 0
    res = _check_outputs(out, ["random", "rules"])
    assert res["config"]["budgets"] == [0, 1, 2]
    assert "rules" in capsys.readouterr().out


def test_discover_generates_the_run_when_asked(tmp_path):
    out = tmp_path / "out"
    assert main(["discover", "--generate", str(ECOM), "--profile", "bench",
                 "--overlay", "bounty_hunters", "--seed", "3", "--set", "users=3000",
                 "--set", "run.days=40", "--methods", "rules", "--k", "3", "--rounds", "2",
                 "--sweep", "0,1", "--seed-draws", "1", "--report-day", "40",
                 "--out", str(out)]) == 0
    assert (out / "run" / "manifest.json").exists()
    _check_outputs(out, ["rules"])


def test_unknown_method_is_a_usage_error(discover_run, tmp_path, capsys):
    try:
        main(["discover", "--run", str(discover_run), "--methods", "nope", "--out",
              str(tmp_path)])
    except SystemExit as e:
        assert e.code == 2
    assert "unknown method" in capsys.readouterr().err

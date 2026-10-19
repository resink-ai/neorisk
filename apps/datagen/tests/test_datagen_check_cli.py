"""datagen check: report.html + checks.json, exit 5 on a failing required check (D86)."""

import json
import math
import shutil
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset

FIX = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"
SECTIONS = ("Counts", "Linkages", "Transitions", "Concentration", "Rejections", "Cohorts",
            "Interference", "Checks")
EXPECTATIONS = """
pack: ring
defaults: {min_sample: 1}
laws: []
expectations:
  - id: exp.signups
    metric: stat.share("bonus_paid", of=["signed_up"])
    target: {between: [0.0, 1.0]}
    source: "test"
    required: true
overlays:
  ring:
    - id: exp.gangs
      metric: stat.cohort_size("gang")
      target: {around: "${ring.size}", tolerance: 0.0}
      source: "overlay config"
      required: true
    - id: exp.intf
      metric: stat.interference(base="bonus_paid", cause="pot")
      target: {reported: true}
      source: "§08"
      required: true
"""


def _ring(tmp_path, expectations=EXPECTATIONS):
    proj = tmp_path / "ring"
    shutil.copytree(FIX / "ring", proj, ignore=shutil.ignore_patterns("out", "__pycache__"))
    (proj / "specs" / "expectations.yaml").write_text(expectations)
    return proj


# ---------------------------------------------------------------------------- reading the page

class _Page(HTMLParser):
    """Per `<h2>` section: its text and its tables (rows of cell texts, header row first)."""

    def __init__(self):
        super().__init__()
        self.sections: dict[str, dict] = {}
        self._cur = None
        self._h2 = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self._h2 = ""
        elif tag == "table" and self._cur is not None:
            self._cur["tables"].append([])
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = ""

    def handle_endtag(self, tag):
        if tag == "h2":
            self._cur = self.sections.setdefault(self._h2, {"text": "", "tables": []})
            self._h2 = None
        elif tag in ("td", "th") and self._row is not None:
            self._row.append(self._cell.strip())
            self._cell = None
        elif tag == "tr" and self._cur is not None:
            self._cur["tables"][-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._h2 is not None:
            self._h2 += data
            return
        if self._cell is not None:
            self._cell += data
        if self._cur is not None:
            self._cur["text"] += data


def _page(html):
    p = _Page()
    p.feed(html)
    return p.sections


def _rows(table, key=0):
    """`{cell `key`: the other cells}` of a table's body rows."""
    return {r[key]: r[:key] + r[key + 1:] for r in table[1:]}


def _events(run_dir, name):
    files = sorted((run_dir / "events" / name).glob("date=*/step-*.parquet"))
    return pl.concat([pl.read_parquet(f) for f in files]) if files else None


def _n(run_dir, name):
    df = _events(run_dir, name)
    return 0 if df is None else df.height


def _top1(values):
    """Top-1% share of a column's non-null values, computed from scratch."""
    vc = values.drop_nulls().value_counts(sort=True)
    counts = sorted(vc[vc.columns[1]].to_list(), reverse=True)
    k = max(1, math.ceil(len(counts) / 100))
    return f"{100 * sum(counts[:k]) / sum(counts):.1f}%"


# ---------------------------------------------------------------------------- the ring run

@pytest.fixture(scope="module")
def ring_report(tmp_path_factory):
    proj = _ring(tmp_path_factory.mktemp("check"))
    run_to_dataset(proj, "sample", [], threads=2)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    rc = main(["check", str(proj), "--profile", "sample", "--overlay", "ring"])
    return proj, rc


def test_check_writes_the_report_and_passes(ring_report):
    proj, rc = ring_report
    assert rc == 0
    out = proj / "reports" / "sample-s7+ring"
    html = (out / "report.html").read_text()
    for section in SECTIONS:
        assert f">{section}<" in html, section
    checks = json.loads((out / "checks.json").read_text())
    assert checks["ok"] is True and checks["interference"]["shared"] == ["pot"]
    # sections in the order of §02/§16, self-contained (no script, no external resource)
    pos = [html.index(f">{s}<") for s in SECTIONS]
    assert pos == sorted(pos)
    assert "<script" not in html and "http://" not in html and "https://" not in html
    assert checks["run"] == "sample-s7+ring" and checks["pack"] == "ring"
    assert checks["overlays"] == {"ring": {"arrive_day": 0.0, "minions": 2, "share_device": 0.5,
                                           "size": 2, "wait": "2h"}}
    assert {r["id"] for r in checks["results"]} == {"exp.signups", "exp.gangs", "exp.intf",
                                                    "regression"}
    reg = next(r for r in checks["results"] if r["id"] == "regression")
    assert (reg["status"], reg["required"], reg["kind"]) == ("pass", True, "regression")


def test_the_report_sections_hold_the_datasets_values(ring_report):
    proj, _ = ring_report
    run, base = proj / "out" / "sample-s7+ring", proj / "out" / "sample-s7"
    page = _page((proj / "reports" / "sample-s7+ring" / "report.html").read_text())
    assert list(page) == list(SECTIONS)
    stats = json.loads((run / "run_stats.json").read_text())

    counts = _rows(page["Counts"]["tables"][0], key=1)
    for name in ("signed_up", "bonus_paid", "granted", "refused", "refunded"):
        assert counts[name] == ["event", str(_n(run, name))], name
    assert counts["signed_up"] == ["event", "12"]

    # every claim is answered by the pot desk with one granted or refused row
    claims = _n(run, "granted") + _n(run, "refused")
    assert claims == 10
    assert _rows(page["Linkages"]["tables"][0])["claim"] == [str(claims), str(claims), "0"]
    assert "Late messages" in page["Linkages"]["text"]

    per_machine, entries = page["Transitions"]["tables"]
    entry_rows = {(r[0], r[1]): r[2] for r in entries[1:]}
    for m, d in stats["machines"].items():
        for state, n in d["entries"].items():
            assert entry_rows[(m, state)] == str(n)
    gangs = pl.read_parquet(sorted((run / "entities" / "gang").glob("*.parquet")))
    labels = pl.read_parquet(sorted((run / "labels" / "labels_gang").rglob("*.parquet")))
    minions = labels.filter(pl.col("role").cast(pl.String) == "minion")["target_id"].n_unique()
    assert entry_rows[("boss", "new")] == str(gangs.height) == "2"
    assert entry_rows[("minion", "invited")] == str(minions) == "4"
    assert _rows(per_machine)["boss"][0] == str(minions)                  # spawned

    conc = _rows(page["Concentration"]["tables"][0])
    signed = _events(run, "signed_up")
    assert conc["signed_up"] == ["user_id", "12", str(signed["user_id"].n_unique()), "1",
                                 _top1(signed["user_id"])]
    granted = _events(run, "granted")
    assert conc["granted"][:2] == ["who", str(granted.height)]
    assert conc["granted"][-1] == _top1(granted["who"])
    assert conc["refunded"] == ["who", "0", "0", "—", "—"]

    assert _rows(page["Rejections"]["tables"][0]) == {p: [str(n)] for p, n in
                                                      stats["rejects"].items()}

    users = pl.read_parquet(sorted((run / "entities" / "user").glob("*.parquet")))
    n_members = users.filter(pl.col("origin") == "member").height
    gang_row = _rows(page["Cohorts"]["tables"][0])["gang"]
    assert gang_row[:4] == ["ring", "user", str(gangs.height), str(n_members)]
    assert n_members == 6 and gang_row[5] == str(labels.height)
    by_role = {(r[1], r[2]): r[3] for r in page["Cohorts"]["tables"][1][1:]}
    expect = (labels.with_columns(pl.col("role").cast(pl.String),
                                  pl.col("outcome").cast(pl.String))
              .group_by("role", "outcome").len())
    assert by_role == {(r, o): str(n) for r, o, n in expect.iter_rows()}

    facts, events, answered = page["Interference"]["tables"]
    assert _rows(facts)["shared partitions"] == ["pot"]
    assert "knock-on effects" in page["Interference"]["text"]
    ref = _rows(events)["refused"]
    assert ref[:2] == [str(_n(base, "refused")), str(_n(run, "refused"))]
    # D79: every base user claims before the gang arrives, so no answer changed
    assert "Requests answered differently" in page["Interference"]["text"]
    assert answered[1:] == [["pot", "(base run only)", "—", "0"],
                            ["pot", "—", "(with overlay only)", "0"]]

    checks = _rows(page["Checks"]["tables"][0])
    assert {k.split("stat.")[0].split("regression rule")[0] for k in checks} == {
        "exp.signups", "exp.gangs", "exp.intf", "regression"}
    assert all("pass" in v for v in checks.values())


def test_a_check_without_overlays_has_no_interference(ring_report):
    proj, _ = ring_report
    assert main(["check", str(proj), "--profile", "sample"]) == 0
    base = json.loads((proj / "reports" / "sample-s7" / "checks.json").read_text())
    assert base["interference"] is None and [r["id"] for r in base["results"]] == ["exp.signups"]


def test_a_missing_baseline_fails_the_required_interference_check(tmp_path):
    proj = _ring(tmp_path)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring"]) == 5
    checks = json.loads((proj / "reports" / "sample-s7+ring" / "checks.json").read_text())
    st = {r["id"]: r["status"] for r in checks["results"]}
    assert st["exp.intf"] == "missing" and checks["ok"] is False
    html = (proj / "reports" / "sample-s7+ring" / "report.html").read_text()
    assert "interference needs a baseline run" in html            # the row's note is shown
    # usage errors exit 2: overlay parameters that differ from the run's, no such run,
    # a baseline folder that does not exist, a corrupt manifest
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring",
                 "--set", "ring.size=3"]) == 2
    assert main(["check", str(proj), "--profile", "sample"]) == 2
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring",
                 "--baseline", str(tmp_path / "nope")]) == 2
    (proj / "out" / "sample-s7+ring" / "manifest.json").write_text("{not json")
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring"]) == 2


def test_a_baseline_with_other_settings_is_refused(tmp_path):
    proj = _ring(tmp_path)
    base = run_to_dataset(proj, "sample", ["users=5"], threads=2).out_dir
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring",
                 "--baseline", str(base)]) == 2


# ---------------------------------------------------------------------------- exit codes

_ONE = """
pack: ring
defaults: {{min_sample: {min_sample}}}
expectations:
  - id: exp.one
    metric: stat.share("bonus_paid", of=["signed_up"])
    target: {target}
{source}    required: {required}
"""


@pytest.fixture(scope="module")
def base_run(tmp_path_factory):
    proj = _ring(tmp_path_factory.mktemp("exit"))
    run_to_dataset(proj, "sample", [], threads=2)
    return proj


@pytest.mark.parametrize("case, rc, status", [
    ({}, 0, "pass"),
    ({"target": "{gt: 2.0}"}, 5, "fail"),
    ({"min_sample": 10_000}, 5, "inconclusive"),
    ({"source": ""}, 5, "unanchored"),
    ({"target": "{gt: 2.0}", "required": "false"}, 0, "fail"),
    ({"source": "", "required": "false"}, 0, "unanchored"),
])
def test_exit_codes_follow_required_checks(base_run, case, rc, status):
    v = {"min_sample": 1, "target": "{between: [0.0, 1.0]}", "source": '    source: "t"\n',
         "required": "true", **case}
    (base_run / "specs" / "expectations.yaml").write_text(_ONE.format(**v))
    assert main(["check", str(base_run), "--profile", "sample"]) == rc
    checks = json.loads((base_run / "reports" / "sample-s7" / "checks.json").read_text())
    assert [r["status"] for r in checks["results"]] == [status]
    assert checks["ok"] is (rc == 0)


# ---------------------------------------------------------------------------- render alone

def _event_table(name, cols):
    common = [{"name": c, "ref": None} for c in ("event_id", "event_time", "partition_id")]
    return {"kind": "event", "name": name, "columns": common + cols}


def test_concentration_is_the_top_one_percent_of_the_first_ref_column(tmp_path):
    from neorisk_simkit.report import render

    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "schema.json").write_text(json.dumps({"tables": [
        _event_table("hit", [{"name": "amount", "ref": None}, {"name": "user_id", "ref": "user"},
                             {"name": "device_id", "ref": "device"}]),
        _event_table("tick", [{"name": "amount", "ref": None}])]}))
    # user 1 holds 50 rows, user 2 holds 2, 150 users one row each, 10 nulls: 152 distinct
    # values -> the top ceil(1.52) = 2 hold 52 of 202 non-null rows
    users = [1] * 50 + [2] * 2 + list(range(3, 153)) + [None] * 10
    for name, df in (("hit", pl.DataFrame({"amount": list(range(len(users))), "user_id": users,
                                           "device_id": [7] * len(users)})),
                     ("tick", pl.DataFrame({"amount": [1, 2, 3]}))):
        d = tmp_path / "events" / name / "date=2026-03-01"
        d.mkdir(parents=True)
        df.write_parquet(d / "step-000000.parquet")
    page = _page(render(tmp_path, [], interference=None, plan=None))
    rows = _rows(page["Concentration"]["tables"][0])
    assert rows["hit"] == ["user_id", "202", "152", "2", f"{100 * 52 / 202:.1f}%"]
    assert rows["tick"] == ["—", "—", "—", "—", "—"]


def test_render_escapes_every_value(tmp_path):
    from neorisk_simkit.report import render

    evil = "<img src=x onerror=alert(1)>"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "counts": {evil: 3}, "posting_counts": {}, "label_counts": {evil: 2},
        "entity_counts": {evil: 1}, "history_counts": {},
        "pairing": {evil: {"requests": 1, "responses": 1}},
        "late_messages": 0, "pack": evil, "pack_revision": "r", "overlays": {evil: {evil: 1}}}))
    (tmp_path / "run_stats.json").write_text(json.dumps({
        "rejects": {evil: 1},
        "machines": {evil: {"entries": {evil: 1}, "spawned": 0, "rejects": 0, "late": 0,
                            "late_grants": 0}}}))
    results = [{"id": evil, "kind": "expectation", "metric": evil, "value": 0.5,
                "ci": [0.4, 0.6], "n_cases": 10, "censored_share": 0.0,
                "target": {"between": [0, 1]}, "status": "pass", "required": True,
                "source": evil, "note": evil}]
    plan = SimpleNamespace(
        cohorts=(SimpleNamespace(name=evil, overlay=evil, table=evil, partition="p",
                                 labels=evil),),
        partitions=(SimpleNamespace(name="p", table=evil),))
    interference = {"shared": [evil], "identical_base_rows": None, "exogenous_identical": True,
                    "first_contact": evil, "events": {evil: {"base": 1, "with": 2}},
                    "changed_owners": {evil: 1}, "laws_ok": {"base": True, "with": True}}
    html = render(tmp_path, results, interference=interference, plan=plan)
    assert evil not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    page = _page(html)
    for section in ("Counts", "Linkages", "Transitions", "Rejections", "Cohorts",
                    "Interference", "Checks"):
        assert evil in page[section]["text"], section          # shown, as text


# ---------------------------------------------------------------------------- regression gate

_BASE_ONLY = """
pack: ring
defaults: {min_sample: 1}
expectations:
  - id: exp.signups
    metric: stat.share("bonus_paid", of=["signed_up"])
    target: {between: [0.0, 1.0]}
    source: "test"
    required: true
"""


@pytest.fixture(scope="module")
def gated(tmp_path_factory):
    """A ring project whose expectations name no interference, with a base run and runs with
    the sharing `ring` and the quiet (sharing nothing) `quiet` overlays."""
    proj = _ring(tmp_path_factory.mktemp("gate"), _BASE_ONLY)
    run_to_dataset(proj, "sample", [], threads=2)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    run_to_dataset(proj, "sample", [], overlays=["quiet"], threads=2)
    return proj


def _gate(proj, overlay):
    rc = main(["check", str(proj), "--profile", "sample", "--overlay", overlay])
    checks = json.loads((proj / "reports" / f"sample-s7+{overlay}" / "checks.json").read_text())
    return rc, {r["id"]: r for r in checks["results"]}


@pytest.mark.parametrize("overlay", ["ring", "quiet"])
def test_the_regression_rule_gates_check_without_an_interference_expectation(gated, overlay):
    # final review I1: with overlays and a baseline the §08 rule is a required result
    rc, res = _gate(gated, overlay)
    assert rc == 0 and set(res) == {"exp.signups", "regression"}
    assert res["regression"]["status"] == "pass" and res["regression"]["required"] is True


@pytest.mark.parametrize("overlay, change, why", [
    ("ring", {"exogenous_identical": False}, "exogenous draws differ"),
    ("ring", {"laws_ok": {"base": False, "with": True}}, "law fails in the base run"),
    ("quiet", {"identical_base_rows": False}, "base rows differ"),
])
def test_a_broken_regression_rule_exits_5(gated, monkeypatch, overlay, change, why):
    from neorisk_simkit.checks import interference

    real = interference.compare
    monkeypatch.setattr(interference, "compare", lambda a, b, p: {**real(a, b, p), **change})
    rc, res = _gate(gated, overlay)
    assert rc == 5 and res["regression"]["status"] == "fail"
    assert why in res["regression"]["note"]
    assert res["exp.signups"]["status"] == "pass"          # only the rule fails


def test_a_law_broken_in_the_overlay_run_exits_5(tmp_path):
    proj = _ring(tmp_path, _BASE_ONLY)
    run_to_dataset(proj, "sample", [], threads=2)
    out = run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2).out_dir
    m = json.loads((out / "manifest.json").read_text())
    m["laws"]["chk.x"] = {"required": True, "checked": 1, "violations": 1}
    (out / "manifest.json").write_text(json.dumps(m))
    rc, res = _gate(proj, "ring")
    assert rc == 5 and res["regression"]["note"] == ("a required law fails in the run with "
                                                     "overlays")


# ---------------------------------------------------------------------------- expectations file

def test_the_expectations_file_comes_from_datagen_toml(base_run):
    # final review M2: `[project].expectations` names the file (default specs/expectations.yaml)
    v = {"min_sample": 1, "target": "{gt: 2.0}", "source": '    source: "t"\n',
         "required": "true"}
    (base_run / "specs" / "expectations.yaml").write_text(_ONE.format(**v))      # would fail
    v["target"] = "{between: [0.0, 1.0]}"
    (base_run / "checks").mkdir(exist_ok=True)
    (base_run / "checks" / "ring.yaml").write_text(_ONE.format(**v))
    toml = (base_run / "datagen.toml").read_text()
    try:
        (base_run / "datagen.toml").write_text(toml.replace(
            'pack = "specs/pack.py"', 'pack = "specs/pack.py"\nexpectations = "checks/ring.yaml"'))
        assert main(["check", str(base_run), "--profile", "sample"]) == 0
        (base_run / "checks" / "ring.yaml").unlink()
        assert main(["check", str(base_run), "--profile", "sample"]) == 2       # named, absent
    finally:
        (base_run / "datagen.toml").write_text(toml)
    assert main(["check", str(base_run), "--profile", "sample"]) == 5           # the default


def test_a_section_for_an_unknown_overlay_is_refused(base_run):
    # Task 18 review M-3: a misspelt overlay section would silently never apply
    (base_run / "specs" / "expectations.yaml").write_text(EXPECTATIONS.replace("  ring:",
                                                                               "  rnig:"))
    assert main(["check", str(base_run), "--profile", "sample"]) == 2

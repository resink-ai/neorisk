"""Debug mode (emit-time schema checks, state snapshots around rejections) changes nothing:
both example packs give identical rows with and without it (the per-milestone checked run)."""

import dataclasses
from pathlib import Path

import pytest

from neorisk_simkit.engine import simulate
from neorisk_simkit.project import load_project

EX = Path(__file__).resolve().parents[3] / "examples"


@pytest.mark.parametrize(("project", "sets", "overlays"), [
    ("ecommerce", ["users=400", "run.days=20"], ["bounty_hunters"]),
    ("payments", ["customers=150", "run.days=40"], []),
])
def test_debug_and_plain_runs_are_identical(project, sets, overlays):
    pr = load_project(EX / project)
    s = pr.settings(None, sets, overlays)
    plain = simulate(pr.plan(s.overlays), s.config, s.run)
    debug = simulate(pr.plan(s.overlays), s.config, dataclasses.replace(s.run, debug=True))
    for k in plain.events:
        assert plain.events[k].equals(debug.events[k]), k
    for k in plain.entities:
        assert plain.entities[k].equals(debug.entities[k]), k
    assert plain.labels.equals(debug.labels)

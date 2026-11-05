"""The snapshot contract on a built log.

A `<entity>_snapshot` event carries an entity's snapshot-only columns: values known only as of
the extract. Every such row is keyed by its entity (`entity_type` is the entity), there is at
most one per key, and all of them sit at one time N that no other event follows, so no event
carries a value from its future.
"""

from __future__ import annotations

import json
from pathlib import Path

SUFFIX = "_snapshot"


def check_snapshots(root: Path) -> list[str]:
    """Problems with the snapshot events of the built version at `root`; empty when fine."""
    import duckdb

    root = Path(root)
    events = json.loads((root / "schema" / "events.json").read_text())["events"]
    entities = {e["entity"] for e in events if e["kind"] == "entity_created"}
    snaps = [e["name"] for e in events if e["kind"] == "event" and e["name"].endswith(SUFFIX)]
    problems = [f"{s}: snapshot event for unknown entity {s[:-len(SUFFIX)]!r}"
                for s in snaps if s[:-len(SUFFIX)] not in entities]
    snaps = [s for s in snaps if s[:-len(SUFFIX)] in entities]
    if not snaps:
        return problems
    con = duckdb.connect()
    try:
        con.execute(f"CREATE VIEW log AS SELECT * FROM read_parquet('{root / 'log'}/*.parquet')")
        con.execute("CREATE TEMP TABLE snaps (name VARCHAR, entity VARCHAR)")
        con.executemany("INSERT INTO snaps VALUES (?, ?)", [(s, s[:-len(SUFFIX)]) for s in snaps])
        for name, et, n in con.execute(
                "SELECT l.event_type, any_value(l.entity_type), count(*) FROM log l "
                "JOIN snaps s ON s.name = l.event_type WHERE l.entity_type IS DISTINCT FROM "
                "s.entity GROUP BY 1 ORDER BY 1").fetchall():
            problems.append(f"{name}: {n} rows have entity_type {et!r}, not its entity "
                            f"(the owner must be a ref to the entity)")
        for name, n in con.execute(
                "SELECT event_type, count(*) FROM log WHERE event_type IN (SELECT name FROM "
                "snaps) AND entity_key IS NULL GROUP BY 1 ORDER BY 1").fetchall():
            problems.append(f"{name}: {n} rows have a null entity_key")
        for name, key, n in con.execute(
                "SELECT event_type, entity_key, count(*) FROM log WHERE event_type IN (SELECT "
                "name FROM snaps) AND entity_key IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1 "
                "ORDER BY 1, 2 LIMIT 5").fetchall():
            problems.append(f"{name}: {n} snapshot rows for key {key!r}; at most one per key")
        times = [t for (t,) in con.execute(
            "SELECT DISTINCT CAST(event_time AS VARCHAR) FROM log WHERE event_type IN (SELECT name FROM snaps) "
            "ORDER BY 1").fetchall()]
        if len(times) > 1:
            problems.append(f"snapshot events must share one snapshot time N; found "
                            f"{len(times)}, from {times[0]} to {times[-1]}")
        (late,) = con.execute(
            "SELECT count(*) FROM log WHERE event_type NOT IN (SELECT name FROM snaps) AND "
            "event_time > (SELECT min(event_time) FROM log WHERE event_type IN (SELECT name "
            "FROM snaps))").fetchone()
        if late:
            problems.append(f"{late} events come after the snapshot time N; a snapshot must "
                            f"be the last thing the log knows")
    finally:
        con.close()
    return problems

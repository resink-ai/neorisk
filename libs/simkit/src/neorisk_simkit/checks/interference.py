"""The overlay regression rule and the interference report (spec §08, D78, D79, F-01, F-31).

An overlay shares decision-relevant state with the base iff a cohort process sends a boundary
(request or message) to a base partition (`shared_partitions`). `compare` reads the dataset of
a base run and of the same run with the overlay:

- **no sharing**: the base rows (rows of base partitions) must be identical as multisets under
  `canonical_rows` (`identical_base_rows`);
- **sharing**: base users' exogenous draws must be identical (`exogenous_identical`: base
  population entity rows, the base rows of read tables, and the base rows strictly before the
  overlay's first contact with a shared partition), every required law holds in both runs
  (`laws_ok`), and the report lists the changes (`events`, `changed_owners`).

`events` counts every row of a base partition, so rows that cohort members cause on a base
partition (zombie orders on `order`) are counted under "with"; `changed_owners` leaves members
out. Only event tables are compared (postings are not, D78 scope of this check).

`answered_differently` (D79) is, per shared partition, the base requests it answered
differently in the two runs. A base request is a command of the shared partition caused by a
base row (a row of a base owner: cohort requests are left out). It is identified across the
runs as the requester's k-th request to that partition instance: requester `partition_id`,
serving `partition_id` and the ordinal of its causing row in canonical order (event time, then
table). Times, Lamport clocks and `seq` are not part of the identity: after the overlay's first
contact, knock-on effects move a base request's time by milliseconds. Its answer is the set of
event types the partition wrote for it (`granted` or `refused`, `bonus_granted` or
`bonus_rejected`). `changed` counts the requests of both runs whose answer differs, by direction
`"<base answer> -> <answer with overlay>"`; `base_only` and `with_only` count requests found in
one run only (a base owner that made more or fewer requests). A requester that is a created
owner is matched by its dense `partition_id`, which a cohort-created owner of the same partition
earlier in the step can shift (review M-6); such a request shows under `base_only`/`with_only`,
never as answered differently.

`regression_failures` turns the report into the §08 regression rule (D78): sharing ⇒ base
users' exogenous draws identical; no sharing ⇒ base rows identical; either way every required
law holds in both runs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema

PTYPE_SHIFT = 56
KEY = ("event_time", "lamport", "partition_id", "seq")       # canonical order (D13)
# columns whose values legitimately move when overlay rows interleave with base rows: dense
# event ids, causes (raw event ids) and Lamport clocks (a shard's clock advances with every
# cohort command it serves, and owners take it from the responses they receive)
ORDER_COLUMNS = ("event_id", "cause_id", "lamport")


def _ptype(col: str = "partition_id") -> pl.Expr:
    return pl.col(col) // (1 << PTYPE_SHIFT)                     # polars has no `>>` (F-07)


def _cohort_partitions(plan: Any) -> set[str]:
    return {c.partition for c in plan.cohorts}


def shared_partitions(plan: Any) -> tuple[str, ...]:
    """Base partitions that a cohort process sends a boundary to (request or message targets),
    in plan order (D78). Read from the plan's access declarations, never from rows: the sender
    of a cohort's owner-to-owner message is its executor partition, not a user."""
    cohorts = _cohort_partitions(plan)
    bnd = {b.name: b for b in plan.boundaries}
    targets = {bnd[b].to for p in plan.processes if p.partition in cohorts
               for b in (*p.requests.values(), *p.messages.values())}
    return tuple(p.name for p in plan.partitions if p.name in targets and p.name not in cohorts)


def base_ptypes(plan: Any) -> frozenset[int]:
    """`ptype_code`s of the base (non-cohort) partitions."""
    cohorts = _cohort_partitions(plan)
    return frozenset(p.ptype_code for p in plan.partitions if p.name not in cohorts)


def created_namespaces(plan: Any) -> set[str]:
    """The ID namespaces whose values depend on steps and creation order: creatable tables and
    `p.ids` names. Member tables (`user`) are in `plan.namespaces` too, but base rows of a member
    table keep their IDs (members are appended after them, D94), so they are never renamed: an
    overlay that moves a base user's ID must fail the comparison."""
    creatable = {t.name for t in plan.tables if t.creatable}
    members = set(plan.member_tables) - creatable
    return {ns for ns in plan.namespaces if ns not in members}


def _strings(df: pl.DataFrame) -> pl.DataFrame:
    """Categories as strings: two runs may encode them differently, so they sort by value."""
    cats = [c for c, t in df.schema.items() if isinstance(t, (pl.Categorical, pl.Enum))]
    return df.with_columns(pl.col(c).cast(pl.String) for c in cats) if cats else df


def canonical_rows(tables: dict[str, pl.DataFrame], created: set[str],
                   refs: Mapping[str, Mapping[str, str]]) -> dict[str, pl.DataFrame]:
    """The rows of `tables` with step- and creation-dependent IDs canonicalized (D13, D37):

    - `event_id` becomes the row's position in the canonical order `(event_time, lamport,
      partition_id, seq)` over all the given tables;
    - `cause_id` is mapped through the same raw `event_id` -> position map, null when the
      cause is not among the given rows (F-01, D80);
    - the values of every column referencing a namespace of `created` (`refs`: table ->
      {column: referenced namespace}) are renamed by first appearance in canonical order (row
      by row, columns in table order);
    - categories become strings and each table is sorted by all its columns."""
    if not tables:
        return {}
    merged = pl.concat([t.select(*KEY, "event_id", pl.lit(n).alias("_t"),
                                 pl.int_range(pl.len(), dtype=pl.Int64).alias("_i"))
                        for n, t in tables.items()], how="vertical")
    merged = merged.sort([*KEY, "_t", "_i"]).with_row_index("_pos").with_columns(
        pl.col("_pos").cast(pl.Int64))
    pos = merged.select("_t", "_i", "_pos")
    raw = merged.select(pl.col("event_id").alias("_raw"), pl.col("_pos").alias("_cause"))
    if raw["_raw"].n_unique() != raw.height:
        raise ValueError("two rows share a raw event_id")
    out: dict[str, pl.DataFrame] = {}
    for n, t in tables.items():
        t = t.with_columns(pl.lit(n).alias("_t"), pl.int_range(pl.len(), dtype=pl.Int64)
                           .alias("_i")).join(pos, on=["_t", "_i"], how="left")
        t = t.join(raw, left_on="cause_id", right_on="_raw", how="left")
        out[n] = t.with_columns(pl.col("_pos").alias("event_id"),
                                pl.col("_cause").alias("cause_id")).drop("_cause")
    # first appearance of every created ID: (position, column index) over all tables
    seen: dict[str, list[pl.DataFrame]] = {}
    for n, t in out.items():
        for k, c in enumerate(t.columns):
            ns = refs.get(n, {}).get(c)
            if ns in created:
                seen.setdefault(ns, []).append(t.select(
                    pl.col("_pos"), pl.lit(k).alias("_k"), pl.col(c).alias("_v")))
    rename: dict[str, pl.DataFrame] = {}
    for ns, parts in seen.items():
        v = (pl.concat(parts).drop_nulls("_v").sort("_pos", "_k")["_v"]
             .unique(maintain_order=True))
        rename[ns] = pl.DataFrame({"_v": v, "_new": pl.int_range(len(v), dtype=pl.Int64,
                                                                    eager=True)})
    for n, t in out.items():
        for c in t.columns:
            ns = refs.get(n, {}).get(c)
            if ns in created and ns in rename:
                t = (t.join(rename[ns], left_on=c, right_on="_v", how="left")
                     .with_columns(pl.col("_new").alias(c)).drop("_new"))
        t = _strings(t.drop("_t", "_i", "_pos").select(tables[n].columns))
        out[n] = t.sort(t.columns, nulls_last=True)
    return out


def _entity(d: Path, name: str) -> pl.DataFrame | None:
    files = sorted((d / "entities" / name).glob("*.parquet"))
    return pl.concat([pl.read_parquet(f) for f in files]) if files else None


def _same(a: pl.DataFrame | None, b: pl.DataFrame | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if a.columns != b.columns:
        return False
    a, b = _strings(a), _strings(b)
    return a.sort(a.columns, nulls_last=True).equals(b.sort(b.columns, nulls_last=True))


def _same_tables(a: dict[str, pl.DataFrame], b: dict[str, pl.DataFrame]) -> bool:
    return a.keys() == b.keys() and all(a[n].equals(b[n]) for n in a)


def _laws_ok(d: Path) -> bool:
    """Every required law of the run's manifest has no violation (a manifest without a `laws`
    entry cannot show that: False)."""
    laws = json.loads((d / "manifest.json").read_text()).get("laws")
    if not isinstance(laws, Mapping):
        return False
    return all(v["violations"] == 0 for v in laws.values() if v.get("required", True))


def _answers(rows: dict[str, pl.DataFrame], served: list[str]) -> pl.DataFrame:
    """`(_cp, _sp, _k, _ans)`: per base request served by the partition whose event tables are
    `served`, its requester and serving partition, its ordinal among that requester's
    requests to that partition (by causing row time, then table) and its answer (the sorted
    event types written for it, joined by "+")."""
    causes = [t.select(pl.col("event_id").alias("_cid"), pl.lit(n).alias("_ct"),
                       pl.col("event_time").dt.epoch("us").alias("_cti"),
                       pl.col("partition_id").alias("_cp"))
              for n, t in rows.items() if t.height]
    parts = [rows[n].select(pl.col("cause_id").alias("_cid"),
                            pl.col("partition_id").alias("_sp"), pl.lit(n).alias("_e"))
             for n in served if rows[n].height]
    empty = pl.DataFrame(schema={"_cp": pl.Int64, "_sp": pl.Int64, "_k": pl.Int64,
                                 "_ans": pl.String})
    if not causes or not parts:
        return empty
    hits = pl.concat(parts).join(pl.concat(causes), on="_cid", how="inner")
    if not hits.height:
        return empty
    return (hits.group_by("_ct", "_cti", "_cp", "_sp")
            .agg(pl.col("_e").sort().str.join("+").alias("_ans"))
            .sort("_cp", "_sp", "_cti", "_ct")
            .with_columns(pl.int_range(pl.len(), dtype=pl.Int64).over("_cp", "_sp").alias("_k"))
            .select("_cp", "_sp", "_k", "_ans"))


def _answered_differently(rows_a: dict[str, pl.DataFrame], rows_b: dict[str, pl.DataFrame],
                          plan: Any, shared: list[str]) -> dict[str, dict[str, Any]]:
    """Per shared partition: base requests answered differently in the two runs (D79)."""
    out = {}
    for s in shared:
        served = [e.name for e in plan.events if e.group == "events" and e.partition == s
                  and e.name in rows_a]
        key = ["_cp", "_sp", "_k"]
        a, b = _answers(rows_a, served), _answers(rows_b, served)
        both = a.join(b, on=key, how="full", coalesce=True, suffix="_with")
        diff = both.filter(pl.col("_ans").is_not_null() & pl.col("_ans_with").is_not_null()
                           & (pl.col("_ans") != pl.col("_ans_with")))
        changed = (diff.group_by("_ans", "_ans_with").len().sort("_ans", "_ans_with")
                   .iter_rows())
        out[s] = {"changed": {f"{x} -> {y}": n for x, y, n in changed},
                  "base_only": both.filter(pl.col("_ans_with").is_null()).height,
                  "with_only": both.filter(pl.col("_ans").is_null()).height,
                  "matched": both.filter(pl.col("_ans").is_not_null()
                                         & pl.col("_ans_with").is_not_null()).height}
    return out


def regression_failures(rep: Mapping[str, Any]) -> list[str]:
    """Why the §08 regression rule (D78) fails for a `compare` report; empty when it holds:
    with sharing, base users' exogenous draws are identical; without, base rows are identical;
    in both cases every required law holds in the base run and in the run with overlays."""
    why = []
    if rep.get("shared"):
        if rep.get("exogenous_identical") is not True:
            why.append("base users' exogenous draws differ between the runs")
    elif rep.get("identical_base_rows") is not True:
        why.append("base rows differ although the overlay shares no state with the base")
    laws = rep.get("laws_ok") or {}
    for run, name in (("base", "the base run"), ("with", "the run with overlays")):
        if laws.get(run) is not True:
            why.append(f"a required law fails in {name}")
    return why


def _exogenous_entities(base_dir: Path, overlay_dir: Path, plan: Any) -> bool:
    """Base rows of the population tables of base partitions (`origin != "member"`) and the
    first `n_base` rows of every read table (cohort recipes append after them, D94; F-31)."""
    cohorts = _cohort_partitions(plan)
    owned = {p.table: p.name for p in plan.partitions if p.kind == "owner"}
    for pop in plan.populations:
        if owned.get(pop.table) in cohorts:
            continue
        a, b = _entity(base_dir, pop.table), _entity(overlay_dir, pop.table)
        if a is not None:
            a = a.filter(pl.col("origin") != "member")
        if b is not None:
            b = b.filter(pl.col("origin") != "member")
        if not _same(a, b):
            return False
    for t in plan.tables:
        if t.name in owned or t.creatable:
            continue                                       # owner state / created rows
        a, b = _entity(base_dir, t.name), _entity(overlay_dir, t.name)
        if a is None or b is None:
            if (a is None) != (b is None):
                return False
            continue
        if b.height < a.height or not _same(a, b.head(a.height)):
            return False
    return True


def _changed_owners(a: pl.DataFrame, b: pl.DataFrame, unstable: set[str],
                    members: pl.Series) -> int:
    """Base owners whose rows differ as multisets between the runs: the `user_id` column when
    present (then `partition_id`, which a created owner's dense index moves, is not compared;
    cohort members, whose orders run on a base partition, are not base owners), else
    `partition_id`. Columns that move without any change of outcome are not compared:
    `ORDER_COLUMNS` and the columns referencing created namespaces (`unstable`)."""
    owner = "user_id" if "user_id" in a.columns else "partition_id"
    drop = {*ORDER_COLUMNS, *unstable} | ({"partition_id"} if owner == "user_id" else set())
    cols = [c for c in a.columns if c not in drop or c == owner]
    both = pl.concat([_strings(a.select(cols)).with_columns(pl.lit(1).alias("_n")),
                      _strings(b.select(cols)).with_columns(pl.lit(-1).alias("_n"))])
    diff = both.group_by(cols).agg(pl.col("_n").sum()).filter(pl.col("_n") != 0)
    if owner == "user_id":
        diff = diff.filter(~pl.col(owner).is_in(members.to_list()))
    return diff[owner].drop_nulls().n_unique()


def _members(d: Path, plan: Any) -> pl.Series:
    """IDs of the cohort members (`origin == "member"` rows of the member tables)."""
    ids = [e.filter(pl.col("origin") == "member")["id"] for t in plan.member_tables
           if (e := _entity(d, t)) is not None]
    return pl.concat(ids) if ids else pl.Series("id", [], pl.Int64)


def compare(base_dir: Path, overlay_dir: Path, plan: Any) -> dict[str, Any]:
    """The regression check and interference report of one overlay run (D78, D79); `plan` is
    the plan of the run with the overlay. See the module docstring for the keys."""
    base_dir, overlay_dir = Path(base_dir), Path(overlay_dir)
    shared = list(shared_partitions(plan))
    base = base_ptypes(plan)
    part_of = {p.name: p for p in plan.partitions}
    base_events = [e.name for e in plan.events
                   if e.group == "events" and part_of[e.partition].ptype_code in base]
    ev_a, ev_b = read_events(base_dir, base_events), read_events(overlay_dir)
    in_base = _ptype().is_in(sorted(base))
    rows_a = {n: ev_a[n].filter(in_base) for n in base_events}
    rows_b = {n: ev_b[n].filter(in_base) for n in base_events}

    first_contact = None
    if shared:
        cohort = {p.ptype_code for p in plan.partitions} - base
        ids = pl.concat([t.filter(_ptype().is_in(sorted(cohort))).select("event_id")
                         for t in ev_b.values()])["event_id"]
        sp = sorted(part_of[s].ptype_code for s in shared)
        caused = _ptype().is_in(sp) & pl.col("cause_id").is_in(ids.to_list())
        times = [t.filter(caused)["event_time"].min() for t in ev_b.values() if t.height]
        times = [x for x in times if x is not None]
        first_contact = min(times) if times else None

    refs = {t["name"]: {c["name"]: c["ref"] for c in t["columns"] if c.get("ref")}
            for t in load_schema(overlay_dir)["tables"] if t["kind"] == "event"}
    created = created_namespaces(plan)

    def canon(rows: dict[str, pl.DataFrame], before: Any = None) -> dict[str, pl.DataFrame]:
        if before is not None:
            rows = {n: t.filter(pl.col("event_time") < before) for n, t in rows.items()}
        return canonical_rows(rows, created, refs)

    exogenous = (_exogenous_entities(base_dir, overlay_dir, plan)
                 and _same_tables(canon(rows_a, first_contact), canon(rows_b, first_contact)))
    identical = None if shared else _same_tables(canon(rows_a), canon(rows_b))
    members = _members(overlay_dir, plan)

    def changed(n: str) -> int:
        unstable = {c for c, ns in refs.get(n, {}).items() if ns in created}
        return _changed_owners(rows_a[n], rows_b[n], unstable, members)

    return {
        "shared": shared,
        "identical_base_rows": identical,
        "exogenous_identical": exogenous,
        "first_contact": None if first_contact is None else first_contact.isoformat(),
        "events": {n: {"base": rows_a[n].height, "with": rows_b[n].height}
                   for n in base_events},
        "changed_owners": {n: changed(n) for n in base_events},
        "answered_differently": _answered_differently(rows_a, rows_b, plan, shared),
        "laws_ok": {"base": _laws_ok(base_dir), "with": _laws_ok(overlay_dir)},
    }

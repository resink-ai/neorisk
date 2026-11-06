"""Build and verify a synthetic dataset: a `datagen` run's log in, three table designs out.

`build_synthetic` runs the recipe's project (profile, seed, no overlay) into a temp dir, writes
the log, and runs each design's `specs/<design>.sql` over the log alone into `results/`. Then
it grades the results without trusting them:

- the `[[check]]` entries of `dataset.toml` compare results columns with simkit's own tables;
- each question's `oracle.sql` answers it from simkit's tables (`expected/questions/<id>`),
  and every design's answer, from its own tables only, must equal it.

`expected/` also holds the run's labels, cases, golden data and `check.json` (the laws and
expectations); none of them is in the log. `verify_synthetic` rebuilds every design from the
log and compares the tables and the answers. Every DuckDB connection runs in UTC on one
thread, so float sums and row order never vary between builds.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from dataset import names
from dataset.config import DatasetConfig
from dataset.manifest import files_of, lock_diff, lock_of, recipe_sha256, write_json, writer
from dataset.names import resolve
from dataset.snapshots import check_snapshots
from dataset.spider2 import BuildError, _write_parquet
from dataset.tables import TableResult, compare_tables
from neorisk_simkit.io import read
from neorisk_simkit.io.log import LogError, write_log
from refdata.blocks import parse_blocks
from refdata.logviews import attach_log

__all__ = ["BuildError", "build_synthetic", "verify_synthetic"]

ALLOWED = "int32, int64, float64, string, bool, date, timestamp[us, UTC]"


def _ok_type(t: pa.DataType) -> bool:
    return (t in (pa.int32(), pa.int64(), pa.float64(), pa.string(), pa.bool_(), pa.date32())
            or (pa.types.is_timestamp(t) and t.unit == "us" and t.tz == "UTC"))


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET threads = 1")
    return con


def _project(cfg: DatasetConfig) -> Path:
    return Path(names.REPO) / cfg.recipe["project"]


def _table(con: duckdb.DuckDBPyConnection, sql: str, what: str) -> pa.Table:
    """Run `sql`, refuse types outside the contract, and sort the rows by every column."""
    try:
        t = con.sql(sql.rstrip().rstrip(";")).arrow().read_all()
    except duckdb.Error as e:
        raise BuildError(f"{what} fails: {type(e).__name__}: {e}") from e
    bad = [f"{f.name}: {f.type}" for f in t.schema if not _ok_type(f.type)]
    if bad:
        raise BuildError(f"{what}: column types outside the contract ({ALLOWED}): {bad}; "
                         f"cast them in the SQL")
    return t.sort_by([(c, "ascending") for c in t.column_names]).combine_chunks()


def _design(cfg: DatasetConfig, design: str, log_root: Path) -> list[tuple[str, pa.Table]]:
    """One design's tables in block order, built over the log alone. A block may read the
    tables of earlier blocks of the same design."""
    f = cfg.dir / "specs" / f"{design}.sql"
    if not f.exists():
        raise BuildError(f"{cfg.name}: no specs/{design}.sql for design {design!r}")
    try:
        blocks = parse_blocks(f.read_text(), {"table"})
    except ValueError as e:
        raise BuildError(f"{cfg.name}: {design}.sql: {e}") from e
    con = _con()
    try:
        attach_log(con, log_root)
        out = []
        for b in blocks:
            if not b.name.startswith(f"{design}_"):
                raise BuildError(f"{cfg.name}: {design}.sql: table {b.name!r} must start "
                                 f"with {design}_")
            t = _table(con, b.sql, f"{cfg.name}: {b.name}")
            con.register(b.name, t)
            out.append((b.name, t))
        return out
    finally:
        con.close()


def _sim(run: Path) -> duckdb.DuckDBPyConnection:
    """simkit's entity and event tables as views `sim.<table>`, and nothing else."""
    con = _con()
    con.execute("CREATE SCHEMA sim")
    for sub in ("entities", "events"):
        for f in sorted((run / sub).glob("*.parquet")):
            con.execute(f"CREATE VIEW sim.{_q(f.stem)} AS SELECT * FROM read_parquet({_lit(str(f))})")
    return con


def _holding(tables: dict[str, pa.Table]) -> duckdb.DuckDBPyConnection:
    con = _con()
    for n, t in tables.items():
        con.register(n, t)
    return con


def _simulate(cfg: DatasetConfig, out: Path):
    from neorisk_simkit.engine import simulate
    from neorisk_simkit.io import write
    from neorisk_simkit.project import load_project
    from neorisk_simkit.spec import validate

    pr = load_project(_project(cfg))
    s = pr.settings(cfg.recipe["profile"], [], list(cfg.recipe.get("overlay", [])))
    s.run = dataclasses.replace(s.run, seed=int(cfg.recipe["seed"]))
    plan = pr.plan(s.overlays)
    errs = validate(plan)
    if errs:
        raise BuildError(f"{cfg.name}: invalid pack: " + "; ".join(errs))
    write(simulate(plan, s.config, s.run), out,
          provenance={**pr.provenance(), "profile": s.profile, "sets": []})
    return pr, plan


def _simkit_checks(cfg: DatasetConfig, sim: duckdb.DuckDBPyConnection,
                   built: dict[str, pa.Table], design_of: dict[str, str]) -> None:
    named = {c["table"] for c in cfg.checks}
    unknown = sorted(named - set(built))
    if unknown:
        raise BuildError(f"{cfg.name}: [[check]] names tables no design builds: {unknown}")
    unchecked = [t for t in built if t.startswith(("star_dim_", "star_fact_"))
                 and not t.endswith("_lifecycle") and t not in named]
    if unchecked:
        raise BuildError(f"{cfg.name}: star tables without a [[check]] against simkit: "
                         f"{unchecked}")
    sim_tables = {r[0] for r in sim.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'sim'").fetchall()}
    for c in cfg.checks:
        if c["simkit"] not in sim_tables:
            raise BuildError(f"{cfg.name}: [[check]] {c['table']}: no simkit table "
                             f"{c['simkit']!r}")
        mine = {n: t for n, t in built.items() if design_of[n] == design_of[c["table"]]}
        cols = ", ".join(_q(r) for r in c["columns"])
        got_sql = f"SELECT {cols} FROM {_q(c['table'])}" + (
            f" WHERE {c['where']}" if c["where"] else "")
        want_sql = ("SELECT " + ", ".join(f"{_q(s)} AS {_q(r)}" for r, s in c["columns"].items())
                    + f" FROM sim.{_q(c['simkit'])}"
                    + (f" WHERE {c['simkit_where']}" if c["simkit_where"] else ""))
        con = _holding(mine)
        try:
            got = _table(con, got_sql, f"{cfg.name}: [[check]] {c['table']}")
        finally:
            con.close()
        want = _table(sim, want_sql, f"{cfg.name}: [[check]] {c['table']} (simkit side)")
        r = compare_tables(c["table"], want, got, extended=True)
        if not r.ok:
            raise BuildError(f"{cfg.name}: {c['table']} does not match simkit's "
                             f"{c['simkit']}: {r.detail}; missing {r.missing[:2]}, "
                             f"extra {r.extra[:2]}")


def _questions(cfg: DatasetConfig) -> list[str]:
    d = cfg.dir / "specs" / "questions"
    qids = sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []
    want = {"oracle", *cfg.designs}
    for q in qids:
        have = {p.stem for p in (d / q).glob("*.sql")}
        if have != want:
            raise BuildError(f"{cfg.name}: questions/{q} needs exactly "
                             f"{sorted(f'{w}.sql' for w in want)}; has {sorted(have)}")
    return qids


def _ground_truth(run: Path, out: Path) -> None:
    for src, dst in (("labels/labels.parquet", "labels.parquet"),
                     ("cases/cases.parquet", "cases.parquet")):
        if (run / src).exists():
            _write_parquet(pq.read_table(run / src), out / "expected" / dst)
    golden = run / "golden"
    if golden.exists():
        for f in sorted(golden.rglob("*.parquet")):
            _write_parquet(pq.read_table(f), out / "expected" / "golden" / f.relative_to(golden))


def _check_report(cfg: DatasetConfig, pr, plan, run: Path, out: Path) -> None:
    from neorisk_simkit.checks import failed, run_checks
    data = read(run)
    results = run_checks(data, plan.checks)
    exp = pr.specs / "expectations.yaml"
    if exp.exists():
        from neorisk_simkit.checks.stats import check_expectations
        results += check_expectations(data, exp, [])
    bad = failed(results)
    broken = [r.name for r in bad if r.group != "stat"]
    if broken:
        raise BuildError(f"{cfg.name}: the run breaks the pack's laws: {broken}")
    doc = {"pack": data.manifest["pack"], "profile": cfg.recipe["profile"],
           "seed": int(cfg.recipe["seed"]), "overlays": list(cfg.recipe.get("overlay", [])),
           "checks": len(results), "failed": [r.name for r in bad],
           "results": [r.as_dict() for r in results]}
    p = out / "expected" / "check.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n")


def build_synthetic(cfg: DatasetConfig, *, record: bool = False) -> dict:
    final = resolve(f"{cfg.name}/{cfg.version}")
    tmp = final.parent / f".{cfg.version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory() as work:
            run = Path(work) / "run"
            pr, plan = _simulate(cfg, run)
            try:
                write_log(read(run), tmp, owners=cfg.owners)
            except LogError as e:
                raise BuildError(f"{cfg.name}: {e}") from e
            problems = check_snapshots(tmp)
            if problems:
                raise BuildError(f"{cfg.name}: the snapshot events break the contract: "
                                 + "; ".join(problems))
            meta: dict = {"designs": {}, "tables": {}, "questions": []}
            built: dict[str, pa.Table] = {}
            design_of: dict[str, str] = {}
            for design in cfg.designs:
                for name, t in _design(cfg, design, tmp):
                    if name in built:
                        raise BuildError(f"{cfg.name}: table {name!r} is built twice")
                    _write_parquet(t, tmp / "results" / f"{name}.parquet")
                    built[name], design_of[name] = t, design
                    meta["designs"].setdefault(design, []).append(name)
                    meta["tables"][name] = {"design": design,
                                            "columns": [{"name": f.name, "type": str(f.type)}
                                                        for f in t.schema]}
            sim = _sim(run)
            try:
                _simkit_checks(cfg, sim, built, design_of)
                for q in _questions(cfg):
                    sql = (cfg.dir / "specs" / "questions" / q / "oracle.sql").read_text()
                    _write_parquet(_table(sim, sql, f"{cfg.name}: {q}/oracle.sql"),
                                   tmp / "expected" / "questions" / f"{q}.parquet")
                    meta["questions"].append(q)
            finally:
                sim.close()
            _ground_truth(run, tmp)
            _check_report(cfg, pr, plan, run, tmp)
        write_json(tmp / "schema" / "results.json", meta)
        rep = verify_synthetic(cfg, root=tmp)
        if not rep["ok"]:
            failed = [f"{r.name} ({r.detail})" for r in [rep["recipe"], *rep["tables"],
                                                        *rep["questions"]] if not r.ok]
            raise BuildError(f"{cfg.name}: the reference build does not hold up: {failed}")
        files = files_of(tmp)
        manifest = {"name": cfg.name, "version": cfg.version, "kind": cfg.kind,
                    "writer": writer(), "recipe_sha256": recipe_sha256(cfg.dir),
                    "source_sha256": recipe_sha256(_project(cfg)),
                    "counts": {"log": sum(v["rows"] for k, v in files.items()
                                          if k.startswith("log/")),
                               **{f"results/{t}": files[f"results/{t}.parquet"]["rows"]
                                  for t in meta["tables"]},
                               "questions": len(meta["questions"])},
                    "files": files}
        lock_path = cfg.dir / f"{cfg.version}.lock.json"
        if lock_path.exists():
            diff = lock_diff(json.loads(lock_path.read_text()), manifest)
            if diff:
                raise BuildError(f"{cfg.name} {cfg.version}: the build differs from "
                                 f"{lock_path.name} in {diff[:10]}; changed output needs a "
                                 f"new version")
        elif record:
            write_json(lock_path, lock_of(manifest))
        write_json(tmp / "manifest.json", manifest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return manifest


def _failed(name: str, detail: str, rows: int = 0) -> TableResult:
    return TableResult(name, False, rows, 0, detail=detail)


def verify_synthetic(cfg: DatasetConfig, *, root: Path | None = None) -> dict:
    """Every design rebuilt from the log and compared with `results/`, and every design's
    answer to every question compared with `expected/questions/`. Failures are results,
    never raised."""
    root = Path(root) if root else resolve(f"{cfg.name}/{cfg.version}")
    results_json = root / "schema" / "results.json"
    if not results_json.exists():
        raise FileNotFoundError(f"{cfg.name} {cfg.version} is not built under {root.parent}; "
                                f"run: uv run dataset build {cfg.name}")
    meta = json.loads(results_json.read_text())
    recipe = TableResult("recipe", True, 0, 0)
    mf = root / "manifest.json"
    if mf.exists() and json.loads(mf.read_text())["recipe_sha256"] != recipe_sha256(cfg.dir):
        recipe = _failed("recipe", "specs/ or dataset.toml changed since this version was "
                                   "built; rebuild it (or make a new version)")
    tables: list[TableResult] = []
    rebuilt: dict[str, dict[str, pa.Table]] = {}
    for design in cfg.designs:
        want_names = meta["designs"].get(design, [])
        try:
            got = dict(_design(cfg, design, root))
        except BuildError as e:
            tables += [_failed(t, f"the rebuild fails: {e}") for t in want_names]
            continue
        rebuilt[design] = got
        for t in want_names:
            want = pq.read_table(root / "results" / f"{t}.parquet")
            if t not in got:
                tables.append(_failed(t, f"no -- table block in {design}.sql", want.num_rows))
            else:
                tables.append(compare_tables(t, want, got[t], extended=True))
        extra = sorted(set(got) - set(want_names))
        if extra:
            tables.append(_failed(f"{design}.sql", f"blocks for tables not in the results: "
                                                   f"{extra}"))
    questions: list[TableResult] = []
    for q in meta["questions"]:
        want = pq.read_table(root / "expected" / "questions" / f"{q}.parquet")
        for design in cfg.designs:
            name = f"{q}/{design}"
            f = cfg.dir / "specs" / "questions" / q / f"{design}.sql"
            if design not in rebuilt or not f.exists():
                questions.append(_failed(name, "the design did not rebuild" if f.exists()
                                         else f"no questions/{q}/{design}.sql", want.num_rows))
                continue
            con = _holding(rebuilt[design])
            try:
                got = _table(con, f.read_text(), name)
            except BuildError as e:
                questions.append(_failed(name, str(e), want.num_rows))
                continue
            finally:
                con.close()
            questions.append(compare_tables(name, want, got, extended=True))
    return {"ok": recipe.ok and all(r.ok for r in tables + questions), "recipe": recipe,
            "tables": tables, "questions": questions}

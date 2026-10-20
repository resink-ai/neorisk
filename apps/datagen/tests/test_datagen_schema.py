"""datagen schema: the same schema from a pack or a dataset; DDL that a database accepts and
loads the dataset with; Avro / JSON Schema / Arrow / Markdown; --diff and versioning."""

import json
import shutil
from pathlib import Path

import duckdb
import polars as pl
import pytest

from datagen.cli import main

ECOM = Path(__file__).resolve().parents[3] / "examples" / "ecommerce"


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    p = tmp_path_factory.mktemp("s") / "ecommerce"
    shutil.copytree(ECOM, p, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(p), "--overlay", "bounty_hunters", "--set", "users=300",
                 "--set", "run.days=10"]) == 0
    return p


def _out(capsys, *argv) -> str:
    assert main(["schema", *argv]) == 0
    return capsys.readouterr().out


def test_pack_and_dataset_give_the_same_schema(proj, capsys):
    run = proj / "out" / "default-s7+bounty_hunters"
    a = _out(capsys, str(proj), "--overlay", "bounty_hunters", "--format", "json")
    b = _out(capsys, str(run), "--format", "json")
    assert json.loads(a) == json.loads(b)
    plain = json.loads(_out(capsys, str(proj), "--format", "json"))
    assert [t["name"] for t in plain["tables"]] == [t["name"] for t in json.loads(a)["tables"]]


def test_duckdb_ddl_loads_the_dataset(proj, tmp_path):
    run = proj / "out" / "default-s7+bounty_hunters"
    ddl = tmp_path / "all.sql"
    assert main(["schema", str(run), "--format", "sql", "--dialect", "duckdb", "--with-fks",
                 "--load", str(run), "--unified-view", "--single-file", str(ddl)]) == 0
    con = duckdb.connect()
    for stmt in ddl.read_text().split(";\n"):           # runs top to bottom: parents first
        body = "\n".join(x for x in stmt.splitlines() if not x.startswith("--")).strip()
        if body:
            con.execute(body)
    n = con.execute("SELECT count(*) FROM order_placed").fetchone()[0]
    assert n == pl.read_parquet(run / "events" / "order_placed.parquet").height > 0
    total = sum(pl.read_parquet(f).height for f in (run / "events").glob("*.parquet"))
    assert con.execute("SELECT count(*) FROM all_events").fetchone()[0] == total
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO order_returned SELECT * REPLACE (-1 AS amount) "
                    "FROM order_returned LIMIT 1")


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "snowflake", "clickhouse",
                                     "spark"])
def test_every_dialect_renders_every_table(proj, capsys, dialect):
    out = _out(capsys, str(proj), "--format", "sql", "--dialect", dialect)
    assert out.count("CREATE TABLE") == len(json.loads(
        (proj / "out" / "default-s7+bounty_hunters" / "schema" / "schema.json").read_text()
    )["tables"])
    assert "order_placed" in out


def test_other_formats(proj, tmp_path, capsys):
    for fmt, ext in (("avro", "avsc"), ("json-schema", "schema.json"), ("arrow", "txt")):
        d = tmp_path / fmt
        assert main(["schema", str(proj), "--format", fmt, "--out", str(d),
                     "--tables", "order_placed,users"]) == 0
        assert sorted(p.name for p in d.iterdir()) == [f"order_placed.{ext}", f"users.{ext}"]
    avsc = json.loads((tmp_path / "avro" / "order_placed.avsc").read_text())
    types = {f["name"]: f["type"] for f in avsc["fields"]}
    assert types["amount"]["logicalType"] == "decimal" and types["cause_id"][0] == "null"
    js = json.loads((tmp_path / "json-schema" / "order_placed.schema.json").read_text())
    assert js["properties"]["event_id"]["type"] == "string" and "amount" in js["required"]
    md = _out(capsys, str(proj), "--format", "markdown")
    assert "## order_placed (event)" in md and "| sku_id | ref |" in md


def test_diff_requires_a_version_bump(proj, tmp_path, capsys):
    other = tmp_path / "v2"
    shutil.copytree(proj, other, ignore=shutil.ignore_patterns("out", "reports"))
    pack = other / "specs" / "pack.py"
    pack.write_text(pack.read_text().replace(
        '"amount": amount()})\n    p.event("checkout_failed"',
        '"amount": amount(), "coupon": opt(text())})\n    p.event("checkout_failed"').replace(
        "from neorisk_simkit.spec import Latency, Pack, amount, cat, i32, i64, opt, ref",
        "from neorisk_simkit.spec import Latency, Pack, amount, cat, i32, i64, opt, ref, text"))
    assert main(["schema", "--diff", str(proj), str(other)]) == 1
    d = json.loads(capsys.readouterr().out)
    assert d["columns_added"] == ["order_placed.coupon"] and not d["breaking"]
    pack.write_text(pack.read_text().replace("SCHEMA_VERSION = 1", "SCHEMA_VERSION = 2"))
    assert main(["schema", "--diff", str(proj), str(other)]) == 0
    assert main(["schema", "--diff", str(proj), str(proj)]) == 0

"""A tiny source database and project (`shop`) shared by the ingest, rebuild and compare tests."""

import sqlite3
from pathlib import Path

import pytest

PACK = '''
from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("customers", key="customer_id", cols={"ext_id": text(), "city": text()})
    p.event("order_placed", cols={"customer_id": ref("customers"), "order_ext": text(),
                                  "total": amount("EUR"), "note": opt(text())})
    p.event("order_paid", cols={"customer_id": ref("customers"), "order_ext": text()})
'''

SOURCE = '''file = "shop.sqlite"
note = "test fixture"
[tables]
customers = ["cid"]
orders = ["oid"]
'''

INGEST = '''-- the shop fixture
-- entity: customers
SELECT cid AS ext_id, city FROM customers ORDER BY cid;
-- event: order_placed owner=customer_id
SELECT iso_time(placed, '%m/%d/%Y %I:%M:%S %p') AS event_time, cid AS customer_id,
       oid AS order_ext, CAST(ROUND(total * 100) AS INTEGER) AS total, note
FROM orders ORDER BY oid;
-- event: order_paid owner=customer_id
SELECT paid AS event_time, cid AS customer_id, oid AS order_ext
FROM orders WHERE paid IS NOT NULL ORDER BY oid;
'''

VIEWS = '''-- table: customers
SELECT ext_id AS cid, city FROM customers;
-- table: orders
SELECT p.order_ext AS oid, c.ext_id AS cid,
       strftime(p.event_time AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p') AS placed,
       strftime(q.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS paid,
       p.total / 100.0 AS total, p.note
FROM order_placed p JOIN customers c USING (customer_id)
LEFT JOIN order_paid q ON q.order_ext = p.order_ext;
'''

ROWS = [("o1", "c1", "1/2/2021 9:05:00 AM", "2021-01-02 10:00:00", 10.5, "hi"),
        ("o2", "c2", "1/3/2021 12:00:00 PM", None, 3.0, None),
        ("o3", "c1", "1/1/2021 11:59:59 PM", "2021-01-02 00:00:01", 99.99, "")]


def make_db(path: Path, orders=ROWS) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE customers (cid TEXT, city TEXT)")
    con.execute("CREATE TABLE orders (oid TEXT, cid TEXT, placed TEXT, paid TEXT, "
                "total REAL, note TEXT)")
    con.executemany("INSERT INTO customers VALUES (?, ?)", [("c1", "Paris"), ("c2", "Rome")])
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders)
    con.commit()
    con.close()
    return path


@pytest.fixture
def shop(tmp_path):
    """(project dir, source db) for the `shop` fixture."""
    proj = tmp_path / "shop"
    (proj / "specs").mkdir(parents=True)
    (proj / "datagen.toml").write_text("[run]\nseed = 1\ndays = 1.0\n")
    (proj / "specs" / "pack.py").write_text(PACK)
    (proj / "specs" / "source.toml").write_text(SOURCE)
    (proj / "specs" / "ingest.sql").write_text(INGEST)
    (proj / "specs" / "build.sql").write_text(VIEWS)
    return proj, make_db(tmp_path / "shop.sqlite")


REPO = Path(__file__).resolve().parents[3]


def roundtrip(project: str, tmp_path: Path, capsys) -> tuple[dict, Path]:
    """Run `refdata roundtrip examples/<project>` into tmp_path; skip without the source.
    Returns the summary line (as a dict) and the ingested dataset's path."""
    import json

    from refdata import cli
    from refdata.source import load_source
    proj = REPO / "datasets" / project
    db = REPO / "data" / "spider2" / load_source(proj).file
    if not db.exists():
        pytest.skip(f"{db} not fetched (uv run refdata fetch)")
    code = cli.main(["roundtrip", str(proj), "--db", str(db), "--out-dir", str(tmp_path)])
    cap = capsys.readouterr()
    summary = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else {}
    assert code == 0, cap.err[-3000:]
    return summary, tmp_path / project

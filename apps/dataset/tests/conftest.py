"""The `shop` fixture as a dataset folder, with its data root in tmp_path."""

import importlib.util
from pathlib import Path

import pytest

from dataset.config import load

_spec = importlib.util.spec_from_file_location(
    "refdata_fixtures", Path(__file__).resolve().parents[2] / "refdata" / "tests" / "conftest.py")
shop_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shop_fixtures)

Q1 = "SELECT cid, count(*) AS n, sum(total) AS s FROM orders GROUP BY cid ORDER BY cid;\n"


def make_shop(base: Path, mixed: str = "") -> Path:
    d = base / "datasets" / "shop"
    (d / "specs" / "queries").mkdir(parents=True)
    (d / "dataset.toml").write_text('name = "shop"\nversion = "v1"\nkind = "spider2"\n'
                                    f'[recipe]\n[results.mixed]\n{mixed}')
    (d / "datagen.toml").write_text("[run]\nseed = 1\ndays = 1.0\n")
    (d / "specs" / "pack.py").write_text(shop_fixtures.PACK)
    (d / "specs" / "source.toml").write_text(shop_fixtures.SOURCE)
    (d / "specs" / "ingest.sql").write_text(shop_fixtures.INGEST)
    (d / "specs" / "build.sql").write_text(shop_fixtures.VIEWS)
    (d / "specs" / "queries" / "q1.sql").write_text(Q1)
    return d


def snapshot_shop(d: Path, *, ref_owner: bool = True) -> None:
    """Re-cut the shop so `city` travels in a `customers_snapshot` event at N, after every
    order. With `ref_owner=False` the owner is plain text, which breaks the snapshot contract."""
    owner = 'ref("customers")' if ref_owner else "text()"
    pack = d / "specs" / "pack.py"
    pack.write_text(pack.read_text()
                    .replace('cols={"ext_id": text(), "city": text()})',
                             'cols={"ext_id": text()})')
                    + f'    p.event("customers_snapshot", cols={{"customer_id": {owner}, '
                      f'"city": opt(text())}})\n')
    ing = d / "specs" / "ingest.sql"
    ing.write_text(ing.read_text().replace("SELECT cid AS ext_id, city FROM customers",
                                           "SELECT cid AS ext_id FROM customers")
                   + "-- event: customers_snapshot owner=customer_id\n"
                     "SELECT '2021-01-04 00:00:00' AS event_time, cid AS customer_id, city\n"
                     "FROM customers ORDER BY cid;\n")
    b = d / "specs" / "build.sql"
    b.write_text(b.read_text().replace(
        "SELECT ext_id AS cid, city FROM customers;",
        "SELECT c.ext_id AS cid, s.city FROM customers c\n"
        "LEFT JOIN customers_snapshot s ON s.customer_id = c.customer_id;"))


@pytest.fixture
def shop_dataset(tmp_path, monkeypatch):
    """(config, source db) for the shop dataset; NEORISK_DATA_ROOT is tmp_path/root."""
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    d = make_shop(tmp_path)
    return load(d), shop_fixtures.make_db(tmp_path / "shop.sqlite")


@pytest.fixture
def shop_cli(tmp_path, monkeypatch):
    """The shop dataset as the only entry of the catalogue; returns the source db."""
    from dataset import config
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    make_shop(tmp_path)
    monkeypatch.setattr(config, "DATASETS", tmp_path / "datasets")
    return shop_fixtures.make_db(tmp_path / "shop.sqlite")


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Build and verify a real dataset into tmp_path; skip when its source is not fetched.
    Returns (manifest, verify report, {event_type: rows} of the log)."""
    import duckdb

    from dataset.names import REPO
    from dataset.spider2 import build_spider2, verify
    from refdata.source import load_source

    def run(name: str):
        monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
        cfg = load(name)
        db = REPO / "data" / "spider2" / load_source(cfg.dir).file
        if not db.exists():
            pytest.skip(f"{db} not fetched (uv run refdata fetch)")
        manifest = build_spider2(cfg, db)
        log = tmp_path / "root" / name / cfg.version / "log" / "*.parquet"
        types = dict(duckdb.sql(f"SELECT event_type, count(*) FROM read_parquet('{log}') "
                                "GROUP BY 1").fetchall())
        return manifest, verify(cfg), types
    return run


TINY_PACK = '''"""Twenty users buy daily; some change tier once."""
from dataclasses import dataclass

from neorisk_simkit.engine import DAY
from neorisk_simkit.spec import Latency, Pack, amount, cat, ref

NAME = "tiny"
SCHEMA_VERSION = 1


@dataclass
class Config:
    users: int = 20


@dataclass
class User:
    uid: int = 0
    tier: str = "a"
    changed: bool = False


def define(p: Pack) -> None:
    p.entity("users", key="user_id", cols={"tier": cat("a", "b")})
    p.event("tier_changed", cols={"user_id": ref("users"), "tier": cat("a", "b")})
    p.event("purchased", cols={"user_id": ref("users"), "amount": amount()})
    user = p.owner("user", state=User, latency=Latency(0.05, 0.3))
    life = user.process("life", start="buy")

    @life.action
    def buy(ctx, s, cmd):
        ctx.emit("purchased", user_id=s.uid, amount=int(100 + ctx.rng.integers(900)))
        if not s.changed and ctx.rng.random() < 0.3:
            s.changed = True
            ctx.after(3600.0, "change")
        ctx.after(DAY * (0.5 + ctx.rng.random()), "buy")

    @life.action
    def change(ctx, s, cmd):
        s.tier = "b" if s.tier == "a" else "a"
        ctx.emit("tier_changed", user_id=s.uid, tier=s.tier)

    @p.source
    def population(src):
        for i in range(src.cfg.users):
            t = src.rng.uniform(0, 0.5) * DAY
            tier = "a" if i % 2 else "b"
            uid = src.insert("users", at=t, tier=tier)
            src.create("user", at=t, uid=uid, tier=tier)
'''

TINY_TOML = '''name = "tiny"
version = "v1"
kind = "synthetic"

[recipe]
project = "examples/tiny"
profile = "sample"
seed = 7
overlay = []
designs = ["star", "an", "obt"]

[recipe.owners]
purchased = "user_id"
tier_changed = "user_id"

[[check]]
table = "star_dim_users"
simkit = "users"
columns = { user_id = "user_id", tier = "tier", valid_from = "created_at" }
where = "users_sk IN (SELECT min(users_sk) FROM star_dim_users GROUP BY user_id)"

[[check]]
table = "star_dim_users"
simkit = "tier_changed"
columns = { user_id = "user_id", tier = "tier", valid_from = "event_time" }
where = "users_sk NOT IN (SELECT min(users_sk) FROM star_dim_users GROUP BY user_id)"

[[check]]
table = "star_fact_purchase"
simkit = "purchased"
columns = { purchase_id = "event_id", user_id = "user_id", amount = "amount", purchased_at = "event_time" }
'''

TINY_DESIGNS = {
    "star": '''-- table: star_dim_users
WITH v AS (SELECT user_id, tier, created_at AS valid_from FROM users
           UNION ALL SELECT user_id, tier, event_time FROM tier_changed)
SELECT row_number() OVER (ORDER BY user_id, valid_from) AS users_sk, user_id, tier, valid_from,
       lead(valid_from) OVER (PARTITION BY user_id ORDER BY valid_from) AS valid_to,
       lead(valid_from) OVER (PARTITION BY user_id ORDER BY valid_from) IS NULL AS is_current
FROM v;

-- table: star_fact_purchase
SELECT p.event_id AS purchase_id, d.users_sk, p.user_id, p.amount, p.event_time AS purchased_at
FROM purchased p JOIN star_dim_users d ON d.user_id = p.user_id
 AND p.event_time >= d.valid_from AND (d.valid_to IS NULL OR p.event_time < d.valid_to);
''',
    "an": '''-- table: an_users
SELECT user_id, created_at FROM users;

-- table: an_users_tier
SELECT user_id, tier, created_at AS changed_at FROM users
UNION ALL SELECT user_id, tier, event_time FROM tier_changed;

-- table: an_purchase
SELECT event_id AS purchase_id, event_time AS purchased_at FROM purchased;

-- table: an_purchase_amount
SELECT event_id AS purchase_id, amount, event_time AS changed_at FROM purchased;

-- table: an_purchase_by_users
SELECT event_id AS purchase_id, user_id FROM purchased;
''',
    "obt": '''-- table: obt_purchase
SELECT p.event_id AS purchase_id, p.user_id, p.amount, p.event_time AS purchased_at,
       (SELECT t.tier FROM (SELECT user_id, tier, created_at AS at FROM users
                            UNION ALL SELECT user_id, tier, event_time FROM tier_changed) t
        WHERE t.user_id = p.user_id AND t.at <= p.event_time ORDER BY t.at DESC LIMIT 1) AS tier
FROM purchased p;
''',
}

TINY_QUESTIONS = {
    "oracle": '''WITH v AS (SELECT user_id, tier, created_at AS at FROM sim.users
           UNION ALL SELECT user_id, tier, event_time FROM sim.tier_changed)
SELECT (SELECT v.tier FROM v WHERE v.user_id = p.user_id AND v.at <= p.event_time
        ORDER BY v.at DESC LIMIT 1) AS tier, count(*) AS purchases,
       CAST(sum(p.amount) AS BIGINT) AS revenue
FROM sim.purchased p GROUP BY 1;
''',
    "star": '''SELECT d.tier, count(*) AS purchases, CAST(sum(f.amount) AS BIGINT) AS revenue
FROM star_fact_purchase f JOIN star_dim_users d USING (users_sk) GROUP BY 1;
''',
    "an": '''SELECT (SELECT t.tier FROM an_users_tier t WHERE t.user_id = b.user_id
        AND t.changed_at <= p.purchased_at ORDER BY t.changed_at DESC LIMIT 1) AS tier,
       count(*) AS purchases, CAST(sum(a.amount) AS BIGINT) AS revenue
FROM an_purchase p JOIN an_purchase_by_users b USING (purchase_id)
JOIN an_purchase_amount a USING (purchase_id) GROUP BY 1;
''',
    "obt": '''SELECT tier, count(*) AS purchases, CAST(sum(amount) AS BIGINT) AS revenue
FROM obt_purchase GROUP BY 1;
''',
}


def make_tiny(base: Path) -> Path:
    """The tiny project under base/examples/tiny and its dataset under base/datasets/tiny."""
    proj = base / "examples" / "tiny"
    (proj / "specs").mkdir(parents=True)
    (proj / "specs" / "pack.py").write_text(TINY_PACK)
    (proj / "datagen.toml").write_text("[run]\nseed = 7\ndays = 3.0\n\n"
                                       "[profiles.sample]\nconfig = { users = 20 }\n")
    d = base / "datasets" / "tiny"
    (d / "specs" / "questions" / "q1").mkdir(parents=True)
    (d / "dataset.toml").write_text(TINY_TOML)
    for k, v in TINY_DESIGNS.items():
        (d / "specs" / f"{k}.sql").write_text(v)
    for k, v in TINY_QUESTIONS.items():
        (d / "specs" / "questions" / "q1" / f"{k}.sql").write_text(v)
    return d


@pytest.fixture
def tiny_synthetic(tmp_path, monkeypatch):
    """The tiny synthetic dataset as the catalogue's only entry; the repo is tmp_path."""
    from dataset import config, names
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(names, "REPO", tmp_path)
    monkeypatch.setattr(config, "DATASETS", tmp_path / "datasets")
    return make_tiny(tmp_path)

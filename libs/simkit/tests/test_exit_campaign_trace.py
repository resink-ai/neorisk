"""§07 trace 2 (M3 exit): a bounty-hunter campaign against a capped bonus pool."""

import json
from datetime import UTC, datetime, timedelta

import polars as pl
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

T = datetime(2026, 3, 13, 9, 14, tzinfo=UTC)               # day 12 09:14:00
USER_PTYPE, CAMPAIGN_PTYPE = 1, 3                          # user 1, pool 2, campaign 3


def test_campaign_trace(tmp_path):
    res = run_to_dataset(FIXTURES / "campaign_trace", "trace", [], out_dir=tmp_path / "t",
                         threads=2)
    ev = read_events(res.out_dir)
    users = pl.read_parquet(res.out_dir / "entities" / "user")
    # base users in dense order: an owner's partition_id is its partition type << 56 | dense id
    base = (ev["order_placed"].filter(pl.col("partition_id") // (1 << 56) == USER_PTYPE)
            .sort("partition_id")["user_id"].to_list())
    assert sorted(base) == sorted(users.filter(pl.col("origin") != "member")["id"].to_list())
    assert len(base) == 2
    zombies = (ev["order_placed"].filter(pl.col("partition_id") // (1 << 56) == CAMPAIGN_PTYPE)
               .sort("event_time")["user_id"].to_list())
    assert len(zombies) == 3
    z0, z1, z2 = zombies

    # 09:14:00: the pool decides U0, U1 and Z0 in its own heap, in canonical order: the base
    # requests carry the smaller cause lamport, and U0 < U1 by sender key (D61)
    g = ev["bonus_granted"].sort("event_time", "lamport")
    assert g.height == 4                                   # cap: 4 claims of 2,000
    first = g.filter(pl.col("event_time") == T)
    assert first["who"].to_list() == [*base, z0]

    # the campaign is suspended between its claim and the response 0.5 s later: no event or
    # label row of the campaign partition falls strictly inside the window
    labels = pl.read_parquet(sorted((res.out_dir / "labels" / "labels_campaign").rglob("*.parquet")))
    camp = pl.concat([t.filter(pl.col("partition_id") // (1 << 56) == CAMPAIGN_PTYPE)
                      .select("event_time") for t in [*ev.values(), labels] if t.height])
    assert camp.filter((pl.col("event_time") > T)
                       & (pl.col("event_time") < T + timedelta(milliseconds=500))).height == 0
    paid = ev["bonus_paid"].filter(pl.col("user_id") == z0)
    assert paid["event_time"].to_list() == [T + timedelta(milliseconds=500)]

    # Z1 at 12:57 is granted; Z2 at 16:40 finds the cap exhausted and leaves as "attempted"
    stagger = timedelta(hours=3, minutes=43)
    z1_order = ev["order_placed"].filter(pl.col("user_id") == z1)
    assert z1_order["event_time"].to_list() == [T + stagger]
    assert g.filter(pl.col("who") == z1)["event_time"].to_list() == [T.replace(hour=12, minute=57)]
    rej = ev["bonus_rejected"]
    assert rej["who"].to_list() == [z2]
    assert rej["event_time"].to_list() == [T.replace(hour=16, minute=40)]
    last = labels.sort("event_time", "lamport").group_by("target_id").last()
    outcome = dict(zip(last["target_id"].to_list(), last["outcome"].to_list(), strict=True))
    assert outcome[z2] == "attempted" and outcome[z0] == outcome[z1] == "paid"

    # the hunter continues: its join times out (Z2 never reports) and it reaches collecting
    st = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["hunter"]
    assert st["entries"]["collecting"] == 1 and st["late"] == 0

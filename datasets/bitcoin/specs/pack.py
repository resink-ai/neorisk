"""Bitcoin trading: 14 members buy and sell BTC and ETH; two daily price series run alongside.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/bitcoin.md); stage 2 adds the behavior.
A member's region is a snapshot column at N = 2021-08-29, the last price bar.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("tickers", key="ticker_id", cols={"ext_id": text(doc="BTC | ETH")})
    p.entity("members", key="member_id",
             cols={"ext_id": text(doc="Source member_id: md5(n)[:6]"), "first_name": text()})
    p.event("price_published", doc="One daily bar of an exogenous series, at 00:00 of its day",
            cols={"ticker_id": ref("tickers"), "price": f64(doc="Close"), "open": f64(),
                  "high": f64(), "low": f64(),
                  "volume": opt(i64(min=0, doc="Coins; NULL is '-' in the source")),
                  "change_pct": f64(doc="Vendor % change, 2 dp; not derivable from closes")})
    p.event("trade", doc="A member buys or sells; no trade price is stored",
            cols={"member_id": ref("members"), "ticker_id": ref("tickers"),
                  "txn_type": cat("BUY", "SELL"), "quantity": f64(), "percentage_fee": f64(),
                  "txn_id": i64(min=1, doc="Source id: the order of the 28 opening ties")})
    p.event("members_snapshot", doc="State at N: the member's region",
            cols={"member_id": ref("members"), "region": text()})

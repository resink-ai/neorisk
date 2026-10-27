import json
from datetime import UTC, date, datetime

import polars as pl
import pytest

from ethcollect import tables
from ethcollect.connectors import explorer
from ethcollect.connectors.aws_public import connector as aws
from ethcollect.context import Context, FetchError, redact
from ethcollect.sample import cap_transfers, seed_candidates

A = "0x" + "ab" * 20
B = "0x" + "cd" * 20
C = "0x" + "ef" * 20
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"

# Trimmed from real Blockscout/Etherscan answers (2026-10-24).
TXLIST = {"blockNumber": "26267249", "timeStamp": "1792901927", "hash": "0xAA", "from": A,
          "to": USDT, "value": "0", "isError": "0", "methodId": "0xa9059cbb",
          "input": "0xa9059cbb00"}
INTERNAL = {"blockNumber": "26260553", "timeStamp": "1792821419", "transactionHash": "0xBB",
            "from": B, "to": A, "value": "144474461223133750180444", "isError": "1",
            "index": "2"}
TOKENTX = {"blockNumber": "26267248", "timeStamp": "1792901915", "hash": "0xCC", "from": A,
           "to": C, "value": "70000000", "contractAddress": USDT, "tokenDecimal": "6",
           "tokenSymbol": "USDT", "logIndex": "17"}


def _ctx(tmp_path, **kw):
    return Context(out=tmp_path, source="t", since=date(2025, 1, 1), until=date(2026, 1, 1),
                   **kw)


def test_explorer_rows_parse_all_three_kinds():
    ext = explorer._external(TXLIST, 0)
    assert ext["kind"] == "external" and ext["log_index"] == -1 and ext["tx_hash"] == "0xaa"
    assert ext["method_id"] == "0xa9059cbb" and ext["ts"].tzinfo is UTC
    internal = explorer._internal(INTERNAL, 0)
    assert internal["status"] == 0 and internal["log_index"] == 2
    assert round(internal["amount"]) == 144474
    tok = explorer._erc20(TOKENTX, 0)
    assert (tok["asset"], tok["amount"], tok["usd_approx"], tok["to_address"]) == (
        USDT, 70.0, 70.0, C)
    df = tables.frame("transfers", [{**r, "source": "t"} for r in (ext, internal, tok)])
    assert df.height == 3


class FakeExplorer(explorer.Explorer):
    def __init__(self, ctx, pages):
        super().__init__(ctx, explorer.BLOCKSCOUT)
        self.pages, self.calls = pages, []

    def call(self, **params):
        self.calls.append(params)
        return self.pages.get(params.get("action"), [])


def test_etherscan_trace_ids_do_not_collide():
    a = explorer._internal({**INTERNAL, "index": None, "traceId": "1_0"}, 0)
    b = explorer._internal({**INTERNAL, "index": None, "traceId": "10"}, 1)
    assert a["log_index"] != b["log_index"]


def test_history_asks_each_kind_newest_first(tmp_path):
    ex = FakeExplorer(_ctx(tmp_path), {"txlist": [TXLIST], "tokentx": [TOKENTX]})
    rows = ex.history(A, 1, 2, per_kind=5)
    assert [r["kind"] for r in rows] == ["external", "erc20"]
    assert {c["action"] for c in ex.calls} == {"txlist", "txlistinternal", "tokentx"}
    assert all(c["sort"] == "desc" and c["offset"] == 5 for c in ex.calls)


def test_logs_split_a_range_that_hits_the_page_cap(tmp_path):
    ex = FakeExplorer(_ctx(tmp_path), {})
    full = [{"n": i} for i in range(1000)]
    ex.call = lambda **p: full if p["toBlock"] - p["fromBlock"] > 300 else [{"n": 0}]
    got = list(ex.logs(USDT, "0xt", 0, 999, step=1000))
    assert len(got) == 4  # one capped answer for 0-999 -> four 250-block windows


def test_explorer_error_is_raised_and_not_cached(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.http = lambda url, **kw: json.dumps(
        {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}).encode()
    ex = explorer.Explorer(ctx, explorer.ETHERSCAN, apikey="SECRET")
    with pytest.raises(FetchError, match="rate limit"):
        ex.call(module="account", action="txlist", address=A)
    assert not ctx.raw.exists() or not list(ctx.raw.glob("*"))
    empty = json.dumps({"status": "0", "message": "No transactions found", "result": []})
    ctx.http = lambda url, **kw: empty.encode()
    assert ex.call(module="account", action="txlist", address=B) == []


def test_cache_keys_and_records_never_hold_the_api_key(tmp_path):
    ctx = _ctx(tmp_path)
    seen = []
    ctx.http = lambda url, **kw: seen.append(url) or b'{"status":"1","result":[]}'
    ex = explorer.Explorer(ctx, explorer.ETHERSCAN, apikey="SECRET")
    ex.call(module="account", action="txlist", address=A)
    ex.call(module="account", action="txlist", address=A)  # second call: cache hit
    assert len(seen) == 1 and "SECRET" in seen[0]
    assert ctx.record["cache_hits"] == 1
    assert "SECRET" not in redact(seen[0])
    record = ctx.save_record({"apikey": "SECRET", "x": 1}).read_text()
    assert "SECRET" not in record


def test_tables_write_replaces_and_load_dedupes_across_sources(tmp_path):
    rows = tables.label_rows([A], kind="phishing", source="b", trust="low")
    tables.write(tmp_path, "labels", "b", tables.frame("labels", rows))
    tables.write(tmp_path, "labels", "b", tables.frame("labels", rows))  # rerun: replaced
    t = datetime(2026, 1, 1, tzinfo=UTC)
    tr = {"tx_hash": "0x1", "log_index": -1, "block_number": 1, "ts": t, "from_address": A,
          "to_address": B, "kind": "external", "asset": "ETH", "asset_symbol": "ETH",
          "amount": 1.0, "decimals": 18, "usd_approx": None, "method_id": None, "status": 1}
    for src in ("b-src", "a-src"):
        tables.append(tmp_path, "transfers", src, tables.frame("transfers", [{**tr,
                                                                             "source": src}]))
    assert tables.load(tmp_path, "labels").height == 1
    loaded = tables.load(tmp_path, "transfers")
    assert loaded.height == 1 and loaded["source"][0] == "a-src"
    assert loaded.schema["ts"] == pl.Datetime("us", "UTC")


def test_addresses_merge_what_each_source_knows(tmp_path):
    def addr(**kw):
        return {"address": A, "is_contract": None, "first_seen": None, "sample_reason": None,
                "source": "x", **kw}

    tables.write(tmp_path, "addresses", "aws-public", tables.frame(
        "addresses", [addr(sample_reason="random", source="aws-public")]))
    tables.write(tmp_path, "addresses", "rpc", tables.frame(
        "addresses", [addr(is_contract=True, source="rpc")]))
    (row,) = tables.load(tmp_path, "addresses").iter_rows(named=True)
    assert (row["is_contract"], row["sample_reason"], row["source"]) == (
        True, "random", "aws-public,rpc")


def test_aws_transfers_scale_stablecoins_and_leave_unknown_tokens_raw():
    t = datetime(2026, 9, 1, 8)
    tx = pl.DataFrame([{"hash": "0x1", "block_number": 5, "block_timestamp": t,
                        "from_address": A, "to_address": B, "value": 2e18,
                        "receipt_status": 1}])
    def topic(a):  # token_transfers stores from/to as 32-byte topics, as in the real files
        return "0x" + "0" * 24 + a[2:]

    tok = pl.DataFrame([
        {"transaction_hash": "0x2", "log_index": 3, "block_number": 5, "block_timestamp": t,
         "from_address": topic(A), "to_address": topic(B), "value": 5e6, "token_address": USDT},
        {"transaction_hash": "0x3", "log_index": 4, "block_number": 5, "block_timestamp": t,
         "from_address": topic(A), "to_address": topic(B), "value": 7.0, "token_address": C}])
    eth, usdt, other = aws.transfers_from(tx, tok)
    assert eth["amount"] == 2.0 and eth["ts"].tzinfo is UTC
    assert (usdt["from_address"], usdt["to_address"]) == (A.lower(), B.lower())
    assert (usdt["amount"], usdt["usd_approx"], usdt["asset_symbol"]) == (5.0, 5.0, "USDT")
    assert (other["amount"], other["decimals"]) == (7.0, None)


def test_seed_candidates_interleave_kinds_dated_first():
    rows = (tables.label_rows([A], kind="phishing", source="s", trust="low")
            + tables.label_rows([B], kind="phishing", source="s", trust="low",
                                observed_at=date(2026, 1, 1))
            + tables.label_rows([C], kind="sanctioned", source="s", trust="high")
            + tables.label_rows(["0x" + "11" * 20], kind="exchange", source="s", trust="low"))
    import random

    got = seed_candidates(tables.frame("labels", rows), random.Random(0))
    assert got == [B, C, A]  # phishing (dated B), sanctioned C, then phishing A; no exchange


def test_cap_keeps_latest_n_per_sampled_address():
    def t(h, a, b, day):
        return {"tx_hash": h, "block_number": day, "log_index": -1, "kind": "external",
                "from_address": a,
                "to_address": b, "ts": datetime(2026, 1, day, tzinfo=UTC)}

    tr = pl.DataFrame([t("1", A, C, 1), t("2", A, C, 2), t("3", C, A, 3), t("4", B, C, 4)])
    got = cap_transfers(tr, [A], cap=2)
    assert sorted(got["tx_hash"].to_list()) == ["2", "3"]


def test_scan_days_cover_the_window_evenly():
    import random

    days = aws.spread_days(date(2025, 10, 1), date(2026, 10, 1), 30, random.Random(1))
    assert len(days) == 30 and days == sorted(days) and len({d.month for d in days}) == 12


def test_scan_keeps_latest_rows_of_watched_and_picked_addresses():
    def topic(a):
        return "0x" + "0" * 24 + a[2:]

    other = "0x" + "99" * 20
    rows = [{"block_number": b, "log_index": 0, "from_address": topic(A.upper()),
             "to_address": topic(other)} for b in range(1, 8)]
    rows.append({"block_number": 9, "log_index": 0, "from_address": topic(B),
                 "to_address": topic(other)})
    df = pl.DataFrame(rows)
    got, randoms = aws.match_rows(df, {A.lower()}, seed=7, rate=0.0, cap=3, padded=True,
                                  order=["block_number", "log_index"])
    assert got["block_number"].to_list() == [7, 6, 5]  # latest 3 of the watched address
    assert set(got["from_address"]) == {A.lower()} and randoms == set()
    got, randoms = aws.match_rows(df, set(), seed=7, rate=1.0, cap=1, padded=True,
                                  order=["block_number", "log_index"])
    assert randoms == {A.lower(), B, other}  # rate 1 picks every address
    assert aws.picked(A, 7, 1 / 5000) == aws.picked(A, 7, 1 / 5000)  # same pick every day


def test_seed_preference_reorders_within_a_kind_but_kinds_still_alternate():
    import random

    rows = (tables.label_rows([A, B], kind="frozen", source="s", trust="high")
            + tables.label_rows([C], kind="phishing", source="s", trust="low"))
    busy = {B}
    got = seed_candidates(tables.frame("labels", rows), random.Random(0),
                          prefer=lambda a: a not in busy)
    assert got == [B, C, A]  # busy B first among frozen, then phishing takes its turn

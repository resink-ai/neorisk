"""Request op (D67, D83), create_owner, and a dispute as a spawned child the payment joins on
(D51). Review Focus 3: a response exactly at the timeout is in time."""

import json

import polars as pl
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.machine.compile import MAX_COMMAND_KIND, response_kinds
from neorisk_simkit.machine.layout import FIRST_RESPONSE_KIND
from neorisk_simkit.machine.spec import build_machines
from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.pack import PackError
from neorisk_simkit.spec.plan import build_plan
from neorisk_simkit.spec.types import i64

S = 1_000_000


def _run(tmp_path, overrides=()):
    res = run_to_dataset(FIXTURES / "mx_pay", "sample", list(overrides),
                         out_dir=tmp_path / "run", threads=2)
    ev = read_events(res.out_dir)
    pays = pl.read_parquet(res.out_dir / "entities" / "payment").select(
        pl.col("id").alias("payment_id"), "amount", pl.col("created_at").alias("t0"))
    return res, ev, pays


def _t(col):
    return col.cast(pl.Int64)


def test_granted_requests_store_the_response_and_create_receipts(tmp_path):
    res, ev, pays = _run(tmp_path)
    ok = pays.filter(pl.col("amount") <= 500)
    cap = ev["captured"].join(pays, on="payment_id", suffix="_p")
    assert set(cap["payment_id"]) == set(ok["payment_id"])
    assert (cap["amount"] == cap["amount_p"]).all()          # stored from the response
    assert set(ev["declined"]["payment_id"]) == set(pays["payment_id"]) - set(ok["payment_id"])
    assert ev["receipt_issued"].height == ok.height
    m = json.loads((res.out_dir / "manifest.json").read_text())
    assert m["pairing"]["capture"]["requests"] == m["pairing"]["capture"]["responses"] == 6


def test_late_responses_take_the_timeout_branch_and_release_grants(tmp_path):
    res, ev, pays = _run(tmp_path, ["latency_ms=1500"])
    assert ev["timed_out"].height == 6 and ev["captured"].height == 0
    granted = pays.filter(pl.col("amount") <= 500)
    assert ev["voided"].height == granted.height                  # never silently consumed
    assert sorted(ev["voided"]["amount"].to_list()) == sorted(granted["amount"].to_list())
    st = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["pay"]
    assert st["late_grants"] == granted.height


def test_timeout_boundary_is_inclusive(tmp_path):
    _res, ev, _p = _run(tmp_path / "a", ["latency_ms=1000", "timeout=1000ms"])
    assert ev["timed_out"].height == 0
    _res, ev, _p = _run(tmp_path / "b", ["latency_ms=1000", "timeout=999999us"])
    assert ev["timed_out"].height == 6


def test_a_dispute_answered_before_the_join_state_is_not_lost(tmp_path):
    _res, ev, _pays = _run(tmp_path)
    c = ev["captured"].select("payment_id", _t(pl.col("event_time")).alias("tc"))
    d = ev["closed"].select("payment_id", _t(pl.col("event_time")).alias("td")).join(
        c, on="payment_id")
    assert d.height == ev["captured"].height
    assert (d["td"] == d["tc"]).all()                          # joined at once on entry


def test_the_join_waits_for_a_long_dispute(tmp_path):
    _res, ev, _p = _run(tmp_path, ["dispute_len_s=7200"])
    r = ev["dispute_resolved"].select("payment_id", _t(pl.col("event_time")).alias("tr"))
    d = ev["closed"].select("payment_id", _t(pl.col("event_time")).alias("td")).join(
        r, on="payment_id")
    assert d.height > 0 and (d["td"] == d["tr"]).all()


def test_the_join_times_out_and_counts_the_late_dispute(tmp_path):
    res, ev, _p = _run(tmp_path, ["dispute_len_s=172800"])     # two days > the 1d timer
    st = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["pay"]
    assert ev["closed"].height == ev["captured"].height
    assert st["late"] == ev["dispute_resolved"].height


# ---------------------------------------------------------------- build-time checks (no run)
def _pack():
    p = Pack("rq", 1)
    t = p.table("acct", key="acct_id", mutable=True, cols={"n": i64()})
    p.owner("acct", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    r = p.table("rcpt", key="rcpt_id", mutable=True, cols={"n": i64()})
    p.owner("rcpt", table=r, max_live=2)
    p.shard("desk", key="desk", n=1, items=None, state={})
    lat = dist.constant(s=1)
    p.message("void", frm="acct", to="desk", payload={"amount": i64()}, latency=lat)
    p.message("back", frm="desk", to="acct", payload={}, latency=lat)
    p.request("ask", frm="acct", to="desk", payload={"amount": i64()},
              response_payload={"amount": i64()}, responses=("granted", "rejected"),
              latency=lat)
    return p


def _req(**kw):
    args = {"amount": 1, "store": {"amount": "got"}, "release": std.send("void", amount=1)}
    args.update(kw)
    local = args.pop("local", "ask")
    return std.request(local, **{k: v for k, v in args.items() if v is not None})


def _request_errors(req, *, table="rcpt"):
    p = _pack()
    p.machine("m", owner="acct", initial="a", fields={"got": "i64"}).state(
        "a", request={"b": req}, timeout="1s", on_reject="c").state(
        "b", branch={"c": (1.0, None, std.create_owner(table, n=1))}).final("c")
    return build_machines(p)[1]


def test_request_ops_are_validated_against_their_boundary():
    w = "machine m: state 'a': request "
    assert _request_errors(_req()) == []
    assert w + "'void' is not a request sent by partition 'acct'" in _request_errors(
        _req(local="void"))
    assert w + "'ask': ok='yes' is not one of its responses ['granted', 'rejected']" in \
        _request_errors(_req(ok="yes"))
    errs = _request_errors(_req(store={"amt": "lost"}))
    assert w + "'ask': store key 'amt' is not a response field" in errs
    assert w + "'ask': store value 'lost' is not a declared field" in errs
    errs = _request_errors(_req(amount=None, extra=1))
    assert w + "'ask': unknown payload field 'extra'" in errs
    assert w + "'ask': missing payload field 'amount'" in errs
    assert ("machine m: state 'a': send 'void': missing payload field 'amount'"
            in _request_errors(_req(release=std.send("void"))))
    assert ("machine m: state 'b': create_owner('acct') needs the table of an owner partition "
            "without a population") in _request_errors(_req(), table="acct")


def test_response_kinds_fit_the_int16_command_kind():
    n = MAX_COMMAND_KIND - FIRST_RESPONSE_KIND + 1                  # kinds 2 .. 32767
    kinds = response_kinds([("b", str(j)) for j in range(n)])
    assert kinds[("b", "0")] == 2 and kinds[("b", str(n - 1))] == MAX_COMMAND_KIND == 32767
    with pytest.raises(PackError, match="a command kind is at most 32767"):
        response_kinds([("b", str(j)) for j in range(n + 1)])


def _latency_pack(outcomes: int, where: str):
    """One command: a std.send (one latency site) then the entry of a state that draws
    1 + `outcomes` sites — a chain part, or a late response whose release sends."""
    class Mod:
        PACK, SCHEMA_VERSION = "lat", 1

        @staticmethod
        def define(p: Pack, cfg) -> None:
            p.__dict__.update(_pack().__dict__)
            m = p.machine("m", owner="acct", start=p.on_created("acct"), initial="a",
                          fields={"got": "i64"})
            send = std.send("void", amount=1)
            if where == "chain":
                m.state("a", branch={"b": (1.0, None, send)})
            else:
                m.state("a", request={"b": std.request("ask", amount=1, release=send)},
                        timeout="1s", on_reject="z", on_timeout="b")
            outs = {f"o{j}": (0.0, dist.constant(s=1 + j), None) for j in range(outcomes)}
            outs["o0"] = (None, dist.constant(s=1), None)
            m.state("b", branch=outs).final("z", *outs)

    return Mod


def test_a_send_latency_draw_counts_against_the_16_sites_of_its_command(tmp_path):
    for where, cmd in (("chain", "mx_tr_m_0 part 0"), ("request", "mx_rq_m_1")):
        build_plan(_latency_pack(14, where), None, tmp_path)       # 1 + 14 + 1 latency = 16
        with pytest.raises(PackError, match=f"command {cmd} draws from 17 sites"):
            build_plan(_latency_pack(15, where), None, tmp_path)


def test_requests_and_sends_carry_no_sender_of_their_own():
    """The engine stamps the executing owner's id as `cmd.sender` of a request or message
    (D74: a cohort executor's own id); a machine that must name its actor passes it in the
    payload (`std.actor()`), as mx_pay's receipt does with `payment_id`."""
    text = make_run("mx_pay").plan.machine_sources["payment"]
    assert ("out.request_capture(ctx.t, shard=ctx.cfg.x_pay.v0, "
            "tag=mx_tag_payment(0, i, g, 7, 0), amount=s.amount)") in text
    assert "out.send_void(ctx.t, to=ctx.cfg.x_pay.v8, amount=loc.pay__captured[i])" in text
    assert "sender" not in text

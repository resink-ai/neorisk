"""Law factories: each returns a check `fn(d: Data) -> (n_checked, bad_rows)`.

    p.check("payment_lifecycle", laws.lifecycle("payment_id", {
        None: {"payment_authorized"},
        "payment_authorized": {"payment_captured", "payment_expired"}, ...}))
    p.check("refunds_le_captured", laws.sum_le(("refund_issued", "amount"),
                                               ("payment_captured", "amount"), by="payment_id"))

Parameters given as "cfg.<field>" read the run's config. Every law reads the full output in
canonical (seq) order, so "at the time of the event" means "over strictly earlier seq".
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

import polars as pl

from neorisk_simkit.checks import Data

CITE = ("partition_id", "seq", "action_id")
NONE = pl.DataFrame({"detail": []}, schema={"detail": pl.String})


def _union(d: Data, events: Iterable[str], cols: list[str]) -> pl.DataFrame:
    frames = [d.ev(e).select(*CITE, "event_time", "event_type", *cols) for e in events]
    frames = [f for f in frames if f.height]
    if not frames:
        return d.ev(next(iter(events))).select(*CITE, "event_time", "event_type", *cols).clear()
    return pl.concat(frames, how="vertical_relaxed").sort("seq")


def lifecycle(key: str, transitions: dict[str | None, set[str]]):
    """Per `key`, consecutive events (in seq order) follow `transitions`; the first one is in
    `transitions[None]`. Events with a null key are ignored."""
    events = sorted({e for v in transitions.values() for e in v} | {k for k in transitions if k})
    allowed = pl.DataFrame([(a or "", b) for a, bs in transitions.items() for b in bs],
                           schema=["prev", "event_type"], orient="row").with_columns(ok=True)

    def check(d: Data):
        u = _union(d, events, [key]).filter(pl.col(key).is_not_null())
        u = u.with_columns(prev=pl.col("event_type").shift(1).over(key).fill_null(""))
        bad = (u.join(allowed, on=["prev", "event_type"], how="left")
               .filter(pl.col("ok").is_null())
               .select(*CITE, key, pl.format("{} after {}", "event_type", "prev").alias("detail")))
        return u.height, bad
    return check


def _terms(d: Data, by: str, terms: list[tuple], sign: int) -> list[pl.DataFrame]:
    out = []
    for e, c, *where in terms:
        df = d.ev(e)
        if where:
            df = df.filter(where[0])
        out.append(df.select(*CITE, by, (sign * pl.col(c).cast(pl.Int64)).alias("_v")))
    return out


def running_nonneg(by: str, plus: list[tuple], minus: list[tuple], what: str = "balance"):
    """Per `by`, the running total of `plus` minus `minus` amounts never goes negative. Terms
    are `(event, column)` or `(event, column, filter_expr)`."""
    def check(d: Data):
        parts = _terms(d, by, plus, 1) + _terms(d, by, minus, -1)
        u = (pl.concat(parts, how="vertical_relaxed").filter(pl.col(by).is_not_null())
             .sort("seq").with_columns(_run=pl.col("_v").cum_sum().over(by)))
        bad = u.filter(pl.col("_run") < 0).select(
            *CITE, by, pl.format(f"{what} {{}} < 0", "_run").alias("detail"))
        return u.height, bad
    return check


def sum_le(value: tuple[str, str], cap: tuple[str, str], by: str):
    """Per `by`, the running sum of `value` never exceeds the running sum of `cap`."""
    return running_nonneg(by, plus=[cap], minus=[value], what=f"{cap[0]} - {value[0]}")


def holds_resolved(placed: str = "hold_placed", committed: str = "hold_committed",
                   released: str = "hold_released", max_open_days: float = 1.0):
    """Every hold is committed or released exactly once. A hold still open at the end is
    censored only if its owner's case is and it was placed within `max_open_days` of the end."""
    def check(d: Data):
        p = d.ev(placed).select(*CITE, "hold_id", "event_time")
        done = pl.concat([d.ev(committed).select("hold_id"), d.ev(released).select("hold_id")])
        twice = done.filter(pl.col("hold_id").is_duplicated()).unique()
        live = d.cases.filter(pl.col("censored"))["partition_id"].implode()
        recent = pl.col("event_time") >= pl.lit(
            d.end - timedelta(days=max_open_days)).cast(pl.Datetime("us", "UTC"))
        open_ = p.filter(~pl.col("hold_id").is_in(done["hold_id"].implode())
                         & ~(pl.col("partition_id").is_in(live) & recent))
        bad = pl.concat([
            open_.with_columns(detail=pl.format("hold {} never resolved", "hold_id")),
            p.join(twice, on="hold_id").with_columns(
                detail=pl.format("hold {} resolved twice", "hold_id"))]).drop("hold_id",
                                                                             "event_time")
        return p.height, bad
    return check


def reservations_resolved(prefix: str = "reservation"):
    """Every granted reservation is committed or released exactly once, by its TTL; the ones
    whose TTL runs past the end of the run are censored."""
    def check(d: Data):
        g = d.ev(f"{prefix}_granted").select(*CITE, "reservation_id", "event_time",
                                              "expires_in")
        done = pl.concat([d.ev(f"{prefix}_committed").select("reservation_id", "event_time"),
                          d.ev(f"{prefix}_released").select("reservation_id", "event_time")])
        n_done = done.group_by("reservation_id").agg(pl.len().alias("n"),
                                                     pl.col("event_time").max().alias("t"))
        j = g.join(n_done, on="reservation_id", how="left").with_columns(
            due=pl.col("event_time") + pl.duration(seconds=pl.col("expires_in")))
        end = pl.lit(d.end).cast(pl.Datetime("us", "UTC"))
        bad = j.filter((pl.col("n").is_null() & (pl.col("due") < end))
                       | (pl.col("n") > 1) | (pl.col("t") > pl.col("due"))).select(
            *CITE, pl.format("reservation {} resolved {} times, last at {}, due {}",
                             "reservation_id", "n", "t", "due").alias("detail"))
        return g.height, bad
    return check


def pool_within_cap(event: str, amount: str, cap: int | str, period_days: float | None = None):
    """Grants recorded by `event` sum to at most `cap` per period (whole run if None)."""
    def check(d: Data):
        c = d.value(cap)
        df = d.ev(event)
        start = pl.lit(d.start).cast(pl.Datetime("us", "UTC"))
        k = (pl.lit(0) if period_days is None else
             ((pl.col("event_time") - start).dt.total_microseconds()
              // int(period_days * 86_400e6)))
        df = df.sort("seq").with_columns(_p=k).with_columns(
            _run=pl.col(amount).cum_sum().over("_p"))
        bad = df.filter(pl.col("_run") > c).select(
            *CITE, pl.format(f"period {{}} granted {{}} > cap {c}", "_p", "_run").alias("detail"))
        return df.height, bad
    return check


def pairing(request: tuple[str, str], response: tuple[str, str], *, many: bool = False):
    """Every `request` row has exactly one (`many`: at least one) `response` row with the same
    key, not earlier; every response answers a request."""
    (req, rk), (res, sk) = request, response

    def check(d: Data):
        a = d.ev(req).select(*CITE, pl.col(rk).alias("_k"), pl.col("event_time").alias("_t0"))
        b = d.ev(res).select(*CITE, pl.col(sk).alias("_k"), "event_time")
        nb = b.group_by("_k").agg(pl.len().alias("n"), pl.col("event_time").min().alias("t"))
        j = a.join(nb, on="_k", how="left")
        cond = pl.col("n").is_null() | (pl.col("t") < pl.col("_t0"))
        if not many:
            cond = cond | (pl.col("n") > 1)
        bad = j.filter(cond).select(*CITE, pl.format(f"{req} {{}}: {{}} responses", "_k", "n")
                                    .alias("detail"))
        orphan = b.filter(~pl.col("_k").is_in(a["_k"].implode())).select(
            *CITE, pl.format(f"{res} {{}} answers no {req}", "_k").alias("detail"))
        return a.height + b.height, pl.concat([bad, orphan])
    return check


def unique(event: str, cols: list[str]):
    def check(d: Data):
        df = d.ev(event)
        bad = df.filter(pl.struct(cols).is_duplicated()).select(
            *CITE, pl.lit(f"duplicate {cols}").alias("detail"))
        return df.height, bad
    return check


def consecutive(event: str, by: str, col: str, start: int = 0):
    """Per `by`, `col` takes the values start, start+1, ... in seq order (a nonce)."""
    def check(d: Data):
        df = d.ev(event).sort("seq").with_columns(
            _want=pl.int_range(pl.len()).over(by) + start)
        bad = df.filter(pl.col(col) != pl.col("_want")).select(
            *CITE, pl.format(f"{col}={{}} expected {{}}", col, "_want").alias("detail"))
        return df.height, bad
    return check


def not_while_open(forbidden: str, opened: str, closed: list[str], key: str):
    """No `forbidden` event for a `key` between an `opened` event and the next `closed` one
    (for example: no refund while a dispute is open)."""
    def check(d: Data):
        u = _union(d, [forbidden, opened, *closed], [key]).filter(pl.col(key).is_not_null())
        delta = (pl.when(pl.col("event_type") == opened).then(1)
                 .when(pl.col("event_type").is_in(closed)).then(-1).otherwise(0))
        u = u.with_columns(_open=delta.cum_sum().over(key))
        bad = u.filter((pl.col("event_type") == forbidden) & (pl.col("_open") > 0)).select(
            *CITE, key, pl.lit(f"{forbidden} while {opened} is open").alias("detail"))
        return u.height, bad
    return check

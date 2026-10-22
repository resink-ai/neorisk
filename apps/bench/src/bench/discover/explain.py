"""Why is a confirmed bad user bad? Its anomalies: where it sits in the population's tail.

`anomaly_profile` scores every user on every signal, without labels: how much rarer than
`TAIL` its value is, in the signal's suspicious direction (few views per order is suspicious,
many is not). `explain` turns the known labels into weights: the anomalies the confirmed bad
users carry, less those the reviewed good users carry too. A discovery method then follows
only those anomalies, to look-alikes and through connections, rather than ordinary traits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from bench.discover.features import NAMES, user_matrix
from bench.discover.methods.weak import LF_NAMES, votes
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
TAIL = 0.2                    # a value shared by more than this share of users explains nothing
UNDER_MIN_WINDOW_H = 24.0     # an order under the minimum, then a qualifying one within a day
TOP_REASONS = 5

# behaviour features and the direction that is suspicious
FEATURE_SIGNALS = {"near_min_share": 1, "cheapest_share": 1, "views_per_order": -1,
                   "sessions": -1, "max_device_users": 1, "invites_sent": 1, "bonuses": 1,
                   "hours_to_first_order": -1}
RULE_SIGNALS = [f"rule:{n}" for n in LF_NAMES if n != "repeat_buyer"]      # the bad-voting ones
VERIFY_REASONS = ("id_mismatch", "selfie_timeout", "phone_reused", "device_limit")
PROBE_SIGNALS = ["failed_checks", "fail_reasons", *(f"fails:{r}" for r in VERIFY_REASONS),
                 "under_min_then_qualified"]
SIGNALS = [*FEATURE_SIGNALS, *RULE_SIGNALS, *PROBE_SIGNALS]


@dataclass(frozen=True)
class Explanation:
    weights: np.ndarray                   # per signal: how much it explains the known bad
    reasons: dict[int, list[str]]         # per confirmed bad user: its strongest anomalies

    def top(self, n: int = TOP_REASONS) -> list[tuple[str, float]]:
        order = np.argsort(-self.weights, kind="stable")[:n]
        return [(SIGNALS[j], float(self.weights[j])) for j in order if self.weights[j] > 0]


def _probe_matrix(world: World) -> np.ndarray:
    v = world.verifications
    per = (v.group_by("user_id").agg(
        pl.len().alias("failed_checks"), pl.col("reason").n_unique().alias("fail_reasons"),
        *((pl.col("reason") == r).sum().alias(f"fails:{r}") for r in VERIFY_REASONS))
        if v.height else pl.DataFrame(schema={"user_id": pl.Int64}))
    lo = world.min_order_cents
    o = world.orders.select("user_id", "created_at", "amount")
    under = o.filter(pl.col("amount") < lo).group_by("user_id").agg(
        pl.col("created_at").min().alias("t_under"))
    ok = (o.filter(pl.col("amount") >= lo).join(under, on="user_id")
          .filter((pl.col("created_at") > pl.col("t_under"))
                  & ((pl.col("created_at") - pl.col("t_under")).dt.total_seconds()
                     <= UNDER_MIN_WINDOW_H * 3600))
          .select("user_id").unique().with_columns(pl.lit(1.0).alias("under_min_then_qualified")))
    t = world.users.select("user_id").join(per, on="user_id", how="left").join(
        ok, on="user_id", how="left")
    return np.column_stack([t[c].fill_null(0).cast(pl.Float64).to_numpy()
                            if c in t.columns else np.zeros(t.height) for c in PROBE_SIGNALS])


def raw_signals(world: World) -> np.ndarray:
    """One row per user, one column per signal, oriented so that larger is more suspicious."""
    x, _ = user_matrix(world)
    feat = np.column_stack([s * x[:, NAMES.index(n)] for n, s in FEATURE_SIGNALS.items()])
    v = votes(world)
    rules = np.column_stack([(v[:, LF_NAMES.index(n.split(":", 1)[1])] == 1).astype(float)
                             for n in RULE_SIGNALS])
    return np.column_stack([feat, rules, _probe_matrix(world)])


def tail_excess(raw: np.ndarray) -> np.ndarray:
    """-log P(value at least this suspicious), less -log TAIL, floored at 0."""
    n = len(raw)
    out = np.zeros_like(raw, dtype=float)
    for j in range(raw.shape[1]):
        col = raw[:, j]
        ge = n - np.searchsorted(np.sort(col), col, side="left")
        out[:, j] = np.maximum(0.0, np.log(TAIL * n / ge))
    return out


def anomaly_profile(world: World) -> np.ndarray:
    if "anomaly" not in world.cache:
        world.cache["anomaly"] = tail_excess(raw_signals(world))
    return world.cache["anomaly"]


def explain(world: World, known: dict[int, int]) -> Explanation:
    e = anomaly_profile(world)
    bad = [i for i, v in known.items() if v]
    good = [i for i, v in known.items() if not v]
    w = np.zeros(e.shape[1])
    if bad:
        rows = world.index(np.array(bad))
        w = e[rows].mean(axis=0)
        if good:
            w = np.maximum(0.0, w - e[world.index(np.array(good))].mean(axis=0))
        reasons = {}
        for uid, r in zip(bad, rows, strict=True):
            order = np.argsort(-e[r], kind="stable")[:TOP_REASONS]
            reasons[int(uid)] = [SIGNALS[j] for j in order if e[r, j] > 0]
        return Explanation(weights=w, reasons=reasons)
    return Explanation(weights=w, reasons={})


def reason_score(world: World, known: dict[int, int]) -> np.ndarray:
    """How much of the known bad users' anomaly each user carries, from 0 up."""
    w = explain(world, known).weights
    return anomaly_profile(world) @ w / max(w.sum(), 1e-12)

"""Purpose-built data for label-maturity and future-leakage experiments.

Each event has observable features, a final label, and a return delay (days until the bad label
becomes known, like an ACH return). Two leaky columns are planted on purpose:

* ``fut_txn_cnt_30d``: the user's transactions in the 30 days *after* the event (accounts are
  frozen after fraud, so the future goes quiet).
* ``acct_closed_flag``: an export-time account snapshot (closed if the user ever had a bad event).

``*_pit`` columns hold the point-in-time-correct values a production system would see.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

DRIFT_START, DRIFT_END = 100.0, 180.0  # fraud pattern ramps from regime A to regime B


@dataclass(frozen=True)
class TemporalConfig:
    n_events: int = 240_000
    n_users: int = 30_000
    span_days: int = 300
    target_bad_rate: float = 0.03
    delay_median_days: float = 35.0  # slow-to-confirm pattern
    delay_fast_median_days: float = 8.0
    delay_sigma: float = 0.6
    delay_cap_days: float = 90.0
    freeze_prob: float = 0.8
    seed: int = 7


def _count(keys, user, t, lo, hi, k, side):
    """Rows of the same user with time in the window offset [t+lo, t+hi) (side='left')."""
    return np.searchsorted(keys, user * k + t + hi, side=side) - np.searchsorted(
        keys, user * k + t + lo, side=side
    )


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def generate_temporal(cfg: TemporalConfig | None = None) -> pl.DataFrame:
    cfg = cfg or TemporalConfig()
    rng = np.random.default_rng(cfg.seed)
    k = float(cfg.span_days + 500)
    created = rng.uniform(-365, cfg.span_days * 0.85, cfg.n_users)
    t = np.sort(rng.uniform(0, cfg.span_days, cfg.n_events))
    user = np.floor(cfg.n_users * rng.random(cfg.n_events) ** 1.8).astype(np.int64)
    keep = t >= created[user]
    t, user = t[keep], user[keep]
    n = len(t)

    amount = np.exp(rng.normal(3.5 + 0.002 * t, 0.9))  # covariate drift: amounts creep up
    hour = rng.integers(0, 24, n)
    night = (hour < 6).astype(float)
    new_device = (rng.random(n) < 0.08).astype(float)
    mismatch = (rng.random(n) < 0.10).astype(float)
    failed = rng.poisson(0.3, n).astype(float)
    age = t - created[user]

    def cnt7(keys_user, keys_t, qu, qt):
        keys = np.sort(keys_user * k + keys_t)
        return _count(keys, qu, qt, -7.0, 0.0, k, "left")

    cnt_past = cnt7(user, t, user, t).astype(float)

    ramp = np.clip((t - DRIFT_START) / (DRIFT_END - DRIFT_START), 0.0, 1.0)
    w_amt = 1.6 - 1.3 * ramp  # amount matters much less later
    w_night = 0.2 + 1.8 * ramp  # night-time attacks appear later
    w_mm = 2.6 * ramp  # state-mismatch ring appears later
    z = (
        w_amt * (np.log(amount) - 3.5)
        + 1.3 * new_device
        + w_night * night
        + w_mm * mismatch
        + 0.7 * failed
        + 0.6 * np.log1p(cnt_past)
        - 0.003 * age
    )
    lo, hi = -15.0, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _sigmoid(z + mid).mean() > cfg.target_bad_rate:
            hi = mid
        else:
            lo = mid
    bad = rng.random(n) < _sigmoid(z + (lo + hi) / 2)
    # the newer attack pattern (night-time / state mismatch) is slow to be confirmed (returns
    # arrive weeks later), the older pattern is confirmed quickly
    slow = (night + mismatch) > 0
    median = np.where(slow, cfg.delay_median_days, cfg.delay_fast_median_days)
    delay = np.clip(rng.lognormal(np.log(median), cfg.delay_sigma, n), 1.0, cfg.delay_cap_days)

    # accounts are frozen after the first bad event, so their later activity (mostly) vanishes
    first_bad = np.full(cfg.n_users, np.inf)
    np.minimum.at(first_bad, user[bad], t[bad])
    after = t > first_bad[user] + 1.0
    drop = after & (rng.random(n) < cfg.freeze_prob)
    keep = ~drop
    t, user, amount, hour = t[keep], user[keep], amount[keep], hour[keep]
    new_device, mismatch, failed, age = new_device[keep], mismatch[keep], failed[keep], age[keep]
    bad, delay = bad[keep], delay[keep]
    n = len(t)

    keys = user * k + t
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    cnt_stored = _count(sorted_keys, user, t, -7.0, 0.0, k, "left")
    fut = _count(sorted_keys, user, t, 1e-9, 30.0, k, "right")  # (t, t+30d]

    ever_bad = np.zeros(cfg.n_users, dtype=bool)
    ever_bad[user[bad]] = True
    closed_snapshot = ever_bad[user]

    # point-in-time: a user counts as closed only once an earlier bad event has *matured*
    known_at = np.where(bad, t + delay, np.inf)
    # point-in-time: a user counts as closed only once one of their bad events has matured;
    # maturity >= event time, so "earliest maturity <= t" already implies a strictly earlier event
    seen = np.full(cfg.n_users, np.inf)
    np.minimum.at(seen, user[bad], known_at[bad])
    closed_pit = seen[user] <= t

    return pl.DataFrame(
        {
            "event_id": np.arange(n, dtype=np.int64),
            "t_day": t,
            "user_id": user,
            "amount": np.round(amount, 2),
            "hour": hour.astype(np.int64),
            "new_device": new_device,
            "acct_age_days": np.round(age, 1),
            "state_mismatch": mismatch,
            "failed_logins_1d": failed,
            "txn_cnt_7d": cnt_stored.astype(float),
            "fut_txn_cnt_30d": fut.astype(float),
            "acct_closed_flag": closed_snapshot.astype(float),
            "fut_txn_cnt_30d_pit": np.zeros(n),
            "acct_closed_flag_pit": closed_pit.astype(float),
            "label": bad.astype(np.int64),
            "label_delay_days": np.where(bad, delay, np.nan),
        }
    )

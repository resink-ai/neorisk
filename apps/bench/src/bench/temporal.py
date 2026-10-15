"""Label-maturity and future-leakage experiments with one XGBoost configuration."""

import html as _html
from datetime import UTC, datetime

import numpy as np
import polars as pl
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from xgboost import XGBClassifier

from bench.models import _xgb, train_all
from bench.report import _CSS, svg_lines
from bench.temporal_sim import TemporalConfig, generate_temporal

_esc = _html.escape
CLEAN = [
    "amount",
    "hour",
    "new_device",
    "acct_age_days",
    "state_mismatch",
    "failed_logins_1d",
    "txn_cnt_7d",
]
LEAKY = ["fut_txn_cnt_30d", "acct_closed_flag"]
EMBARGOES = [0, 15, 30, 45, 60, 75]
SEEDS = 3  # model seeds averaged in the maturity sweep (data is fixed)


def _arr(df, cols):
    return df.select(cols).to_numpy().astype("float64")


def _fit(train, valid, cols, label, seed=0):
    m = train_all(
        _arr(train, cols),
        train[label].to_numpy(),
        _arr(valid, cols),
        valid[label].to_numpy(),
        names=("xgb",),
        seed=seed,
    )["xgb"]
    if not hasattr(m, "predict_proba"):
        raise RuntimeError(m.error)
    return m


class _Soft:
    """XGBoost trained on soft labels (each row = positive copy with weight q + negative copy)."""

    def __init__(self, est):
        self.estimator = est

    def predict_proba(self, x):
        return self.estimator.predict_proba(x)[:, 1]


def _fit_soft(x_tr, q_tr, x_va, q_va, seed=0):
    def dup(x, q):
        return (
            np.vstack([x, x]),
            np.r_[np.ones(len(x)), np.zeros(len(x))].astype(int),
            np.r_[q, 1 - q],
        )

    xt, yt, wt = dup(x_tr, q_tr)
    xv, yv, wv = dup(x_va, q_va)
    est: XGBClassifier = _xgb(seed, 1.0)
    est.fit(
        xt, yt, sample_weight=wt, eval_set=[(xv, yv)], sample_weight_eval_set=[wv], verbose=False
    )
    return _Soft(est)


def _delay_correction(df, cutoff, window_end_rows):
    """Posterior bad probability q for rows whose label is not (yet) observed.

    q = pi (1 - F(a)) / (1 - pi F(a)) with pi, F estimated per segment (night / mismatch or not)
    on a fully matured cohort (events older than the longest delay).
    """
    seg = ((df["hour"].to_numpy() < 6) | (df["state_mismatch"].to_numpy() > 0)).astype(int)
    t = df["t_day"].to_numpy()
    y = df["label"].to_numpy()
    delay = df["label_delay_days"].fill_nan(None).fill_null(1e9).to_numpy()
    mature = t < cutoff - 90.0
    q = np.zeros(df.height)
    obs = (y == 1) & (t + delay <= cutoff)
    age = cutoff - t
    for s in (0, 1):
        m = mature & (seg == s)
        pi = float(y[m].mean())
        d = np.sort(delay[m & (y == 1)])
        f = np.searchsorted(d, np.clip(age, 0, None), side="right") / max(len(d), 1)
        qs = pi * (1 - f) / (1 - pi * f)
        q = np.where(seg == s, qs, q)
    return np.where(obs, 1.0, q)


def _thin(a, b, max_points=300):
    idx = np.unique(np.linspace(0, len(a) - 1, min(max_points, len(a))).astype(int))
    return a[idx].tolist(), b[idx].tolist()


def _scores(y, p):
    y = np.asarray(y)
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    fx, ty = _thin(fpr, tpr)
    rx, py = _thin(rec, prec)
    return {
        "auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "n": len(y),
        "n_pos": int(y.sum()),
        "base_rate": float(np.mean(y)),
        "roc": {"fpr": fx, "tpr": ty},
        "pr": {"recall": rx, "precision": py},
    }


def _mean_scores(rows):
    out = dict(rows[0])
    for k in ("auc", "pr_auc"):
        out[k] = float(np.mean([r[k] for r in rows]))
    return out


def run_temporal(
    cfg: TemporalConfig | None = None,
    *,
    cutoff: float = 180.0,
    test_days: float = 30.0,
    valid_days: float = 20.0,
    seed: int = 0,
) -> dict:
    cfg = cfg or TemporalConfig()
    df = generate_temporal(cfg)
    delay = df["label_delay_days"].fill_nan(None).fill_null(1e9).to_numpy()
    t = df["t_day"].to_numpy()
    # label as known at the cutoff: a bad event only shows once its return has arrived
    df = df.with_columns(
        label_obs=pl.Series(((df["label"].to_numpy() == 1) & (t + delay <= cutoff)).astype(int))
    )
    test = df.filter((pl.col("t_day") >= cutoff) & (pl.col("t_day") < cutoff + test_days))
    pool = df.filter(pl.col("t_day") < cutoff)

    out: dict = {"config": cfg.__dict__ | {"cutoff": cutoff, "test_days": test_days}}
    d = df["label_delay_days"].fill_nan(None).drop_nulls().to_numpy()
    out["delay"] = {
        "p50": float(np.percentile(d, 50)),
        "p90": float(np.percentile(d, 90)),
        "p95": float(np.percentile(d, 95)),
        "p99": float(np.percentile(d, 99)),
        "cdf_x": list(range(0, 91, 3)),
        "cdf_y": [float((d <= x).mean()) for x in range(0, 91, 3)],
    }
    out["data"] = {
        "n": df.height,
        "bad_rate": float(df["label"].mean()),
        "n_users": int(df["user_id"].n_unique()),
        "span_days": cfg.span_days,
    }

    # observed vs final bad rate by event week in the training pool
    weeks = []
    for w in range(int(cutoff // 7)):
        s = pool.filter((pl.col("t_day") >= 7 * w) & (pl.col("t_day") < 7 * (w + 1)))
        if s.height:
            weeks.append((7 * w + 3.5, float(s["label"].mean()), float(s["label_obs"].mean())))
    out["weekly"] = weeks

    # --- part 1: label maturity ---------------------------------------------------------
    def split(window_end):
        tr = pool.filter(pl.col("t_day") < window_end - valid_days)
        va = pool.filter(
            (pl.col("t_day") >= window_end - valid_days) & (pl.col("t_day") < window_end)
        )
        return tr, va

    y_test = test["label"].to_numpy()
    sweep = []
    for m in EMBARGOES:
        tr, va = split(cutoff - m)
        sc = _mean_scores(
            [
                _scores(
                    y_test,
                    _fit(tr, va, CLEAN, "label_obs", seed + i).predict_proba(_arr(test, CLEAN)),
                )
                for i in range(SEEDS)
            ]
        )
        sc.update(
            embargo=m,
            train_rows=tr.height,
            train_bad_rate_obs=float(tr["label_obs"].mean()),
            train_bad_rate_final=float(tr["label"].mean()),
        )
        sweep.append(sc)
    out["sweep"] = sweep

    # delayed-feedback correction: keep all recent rows, replace unobserved zeros by soft labels
    q_all = _delay_correction(df, cutoff, None)
    qs = (
        pool.select("event_id")
        .join(pl.DataFrame({"event_id": df["event_id"], "q": q_all}), on="event_id", how="left")[
            "q"
        ]
        .to_numpy()
    )
    tr_mask = pool["t_day"].to_numpy() < cutoff - valid_days
    x_a, x_b = (
        _arr(pool.filter(pl.Series(tr_mask)), CLEAN),
        _arr(pool.filter(pl.Series(~tr_mask)), CLEAN),
    )
    out["corrected"] = _mean_scores(
        [
            _scores(
                y_test,
                _fit_soft(x_a, qs[tr_mask], x_b, qs[~tr_mask], seed + i).predict_proba(
                    _arr(test, CLEAN)
                ),
            )
            for i in range(SEEDS)
        ]
    )

    # validation strategy: random split on matured final labels vs out-of-time
    rng = np.random.default_rng(seed)
    pool_f = pool.filter(pl.col("t_day") < cutoff - 75)
    msk = rng.random(pool_f.height) < 0.8
    tr_r, te_r = pool_f.filter(pl.Series(msk)), pool_f.filter(pl.Series(~msk))
    va_r = tr_r.sample(fraction=0.15, seed=seed)
    mod = _fit(tr_r, va_r, CLEAN, "label", seed)
    out["validation"] = {
        "random_split": _scores(te_r["label"].to_numpy(), mod.predict_proba(_arr(te_r, CLEAN))),
    }
    tr, va = split(cutoff - 75)
    mod_oot = _fit(tr, va, CLEAN, "label", seed)
    p_oot = mod_oot.predict_proba(_arr(test, CLEAN))
    out["validation"]["oot"] = _scores(y_test, p_oot)

    # evaluating on immature test labels understates the metric
    ev = df.filter((pl.col("t_day") >= cutoff) & (pl.col("t_day") < cutoff + test_days))
    t_ev = ev["t_day"].to_numpy()
    dl = ev["label_delay_days"].fill_nan(None).fill_null(1e9).to_numpy()
    y_imm = ((ev["label"].to_numpy() == 1) & (t_ev + dl <= cutoff + test_days)).astype(int)
    out["eval_bias"] = {
        "final": _scores(ev["label"].to_numpy(), p_oot),
        "immature": _scores(y_imm, p_oot),
    }

    # --- part 2: future leakage ---------------------------------------------------------
    tr, va = split(cutoff - 75)
    mats = {}
    for name, cols in (("clean", CLEAN), ("leaky", CLEAN + LEAKY)):
        mod = _fit(tr, va, cols, "label", seed)
        offline = mod.predict_proba(_arr(test, cols))
        # serving: leak columns replaced by what exists at event time (point-in-time values)
        srv = test
        if name == "leaky":
            srv = test.with_columns(
                fut_txn_cnt_30d=pl.col("fut_txn_cnt_30d_pit"),
                acct_closed_flag=pl.col("acct_closed_flag_pit"),
            )
        serving = mod.predict_proba(_arr(srv, cols))
        # in-time random split on the same pool (what a careless notebook would report)
        mod_r = _fit(tr_r, va_r, cols, "label", seed)
        mats[name] = {
            "random_split": _scores(
                te_r["label"].to_numpy(), mod_r.predict_proba(_arr(te_r, cols))
            ),
            "oot_offline": _scores(y_test, offline),
            "oot_serving": _scores(y_test, serving),
            "importance": {
                c: float(v) for c, v in zip(cols, mod.estimator.feature_importances_, strict=True)
            },
        }
    out["leak"] = mats

    # detection: univariate AUC, point-in-time recompute mismatch, ablation
    trn = tr["label"].to_numpy()
    det = []
    pit_of = {"fut_txn_cnt_30d": "fut_txn_cnt_30d_pit", "acct_closed_flag": "acct_closed_flag_pit"}
    base = mats["leaky"]["oot_offline"]["pr_auc"]
    for c in CLEAN + LEAKY:
        a = float(roc_auc_score(trn, tr[c].to_numpy()))
        pit = pit_of.get(c)
        mism = float((tr[c].to_numpy() != tr[pit].to_numpy()).mean()) if pit else 0.0
        det.append({"feature": c, "uni_auc": max(a, 1 - a), "pit_mismatch": mism})
    out["detect"] = det
    abl = {}
    for c in LEAKY:
        cols = [x for x in CLEAN + LEAKY if x != c]
        mod = _fit(tr, va, cols, "label", seed)
        abl[c] = _scores(y_test, mod.predict_proba(_arr(test, cols)))["pr_auc"] - base
    out["ablation"] = abl
    out["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return out


# ----------------------------------------------------------------------------- report
def _chart(series, *, xmax, ymax, xlabel, ylabel, vlines=(), width=520, height=320, pct=False):
    ml, mr, mt, mb = 56, 14, 14, 46
    pw, ph = width - ml - mr, height - mt - mb

    def px(x):
        return ml + min(max(x / xmax, 0.0), 1.0) * pw

    def py(y):
        return mt + (1 - min(max(y / ymax, 0.0), 1.0)) * ph

    o = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for i in range(6):
        fx, fy = xmax * i / 5, ymax * i / 5
        o.append(
            f'<line x1="{px(fx):.1f}" y1="{mt}" x2="{px(fx):.1f}" y2="{mt + ph}" stroke="var(--grid)"/>'
            f'<line x1="{ml}" y1="{py(fy):.1f}" x2="{ml + pw}" y2="{py(fy):.1f}" stroke="var(--grid)"/>'
            f'<text x="{px(fx):.1f}" y="{mt + ph + 16}" text-anchor="middle">{fx:g}</text>'
            f'<text x="{ml - 8}" y="{py(fy) + 4:.1f}" text-anchor="end">'
            f"{(f'{fy * 100:.0f}%' if pct else f'{fy:.3g}')}</text>"
        )
    for v, label in vlines:
        o.append(
            f'<line x1="{px(v):.1f}" y1="{mt}" x2="{px(v):.1f}" y2="{mt + ph}" '
            'stroke="var(--muted)" stroke-dasharray="5 4"/>'
            f'<text x="{px(v) + 4:.1f}" y="{mt + 12}">{_esc(label)}</text>'
        )
    for s in series:
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(s["xs"], s["ys"], strict=True))
        o.append(
            f'<polyline points="{pts}" fill="none" stroke="{s["color"]}" stroke-width="2" '
            f'stroke-linejoin="round"><title>{_esc(s["name"])}</title></polyline>'
        )
        if s.get("dots"):
            o += [
                f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5" fill="{s["color"]}"/>'
                for x, y in zip(s["xs"], s["ys"], strict=True)
            ]
    o.append(
        f'<text x="{ml + pw / 2}" y="{height - 8}" text-anchor="middle">{_esc(xlabel)}</text>'
        f'<text transform="translate(14 {mt + ph / 2}) rotate(-90)" text-anchor="middle">'
        f"{_esc(ylabel)}</text></svg>"
    )
    return "".join(o)


_TXT = {
    "zh": {
        "title": "标签成熟与未来泄漏实验",
        "intro": (
            "专门构造的合成交易数据（{n:,} 笔、{u:,} 个用户、{d} 天，坏样本率 {br:.1%}），"
            "坏样本要等退回到达才被标记（中位 {p50:.0f} 天，95 分位 {p95:.0f} 天，类似 ACH 退回）。"
            "全程使用同一套 XGBoost 参数，只改变训练/评估方式与特征。第 {cut:.0f} 天为训练截止，"
            "之后 {td:.0f} 天为 out-of-time 测试集。"
        ),
        "setup_h": "数据中植入了什么",
        "setup": [
            "概念漂移：旧模式（大额、新设备、登录失败）逐渐减弱，新模式（夜间、异地状态）在第 100–180 天出现。",
            "标签延迟：新模式确认很慢（中位 35 天），旧模式确认快（中位 8 天）。",
            "泄漏列 fut_txn_cnt_30d：事件之后 30 天内该用户的交易数（欺诈账户被冻结后活动消失）。",
            "泄漏列 acct_closed_flag：导出时刻的账户状态快照（出过坏样本则为已关闭）。",
        ],
        "p1": "第一部分：标签成熟度与 out-of-time 测试",
        "delay_h": "退回延迟分布（累计占比）",
        "weekly_h": "各周事件的坏账率：最终 vs 截止日已观察到",
        "weekly_note": (
            "越靠近截止日，已观察到的坏账率越低，因为很多坏样本还没退回，这些行会被当成好样本。"
            "更隐蔽的是缺失并不均匀：确认慢的新模式缺得最多，最新的数据恰恰最缺新模式的标签。"
        ),
        "val_h": "验证方式：随机划分 vs out-of-time",
        "val_cols": ["验证方式", "ROC-AUC", "PR-AUC", "说明"],
        "val_rand": "随机划分（成熟数据内）",
        "val_oot": "Out-of-time（截止日后 30 天）",
        "val_rand_n": "同一时期、同一模式，虚高",
        "val_oot_n": "更接近上线真实表现",
        "bias_h": "评估也要用成熟标签",
        "bias_cols": ["测试标签", "正样本", "坏账率", "PR-AUC"],
        "bias_final": "最终标签（等到全部成熟）",
        "bias_imm": "测试期结束时已知标签（未成熟）",
        "sweep_h": "训练数据的成熟窗口（embargo）与 OOT 表现",
        "sweep_note": (
            "横轴：训练只用距截止日至少这么多天的事件。窗口为 0 即直接使用所有已知标签。"
            "漂移存在时，等越久标签越完整，但数据越旧；所以单纯等待并不划算。"
            "虚线为延迟校正（保留近期数据，把未观察到的 0 换成按延迟分布估计的软标签）。"
            "三个模型随机种子取平均，差异较小的位置不要过度解读。"
        ),
        "sweep_cols": [
            "成熟窗口(天)",
            "训练行数",
            "训练集坏账率(已知)",
            "(最终)",
            "OOT ROC-AUC",
            "OOT PR-AUC",
        ],
        "corr": "延迟校正（软标签）",
        "p2": "第二部分：未来信息泄漏",
        "leak_h": "同一模型在三种评估下的结果",
        "leak_cols": [
            "特征集",
            "随机划分 PR-AUC",
            "OOT 离线 PR-AUC",
            "OOT 上线(point-in-time) PR-AUC",
            "上线 ROC-AUC",
        ],
        "clean": "干净特征（7 个）",
        "leaky": "干净 + 2 个泄漏列",
        "leak_note": (
            "离线（含泄漏列的历史数据）看起来极好，且 OOT 也没有暴露问题，因为泄漏列在测试期同样"
            "来自未来。只有按上线时能拿到的 point-in-time 取值重算，才会崩塌（PR-AUC 低于基线）。"
        ),
        "pr_h": "ROC 与 PR 曲线：干净模型 vs 含泄漏模型（离线、上线）",
        "roc": "ROC 曲线",
        "pr": "PR 曲线",
        "base": "基线坏账率",
        "c_clean": "干净（上线）",
        "c_leak_off": "含泄漏（离线）",
        "c_leak_srv": "含泄漏（上线）",
        "det_h": "怎么发现泄漏",
        "det_cols": ["特征", "单特征 AUC", "point-in-time 重算不一致率", "含泄漏模型重要度"],
        "det_note": (
            "三道检查：(1) 单特征 AUC 异常高；(2) 用 t 时刻之前的数据重算特征并与存储值对比，"
            "不一致就是用了未来信息；(3) 删掉该特征再评估 OOT，指标大幅下降说明模型依赖它。"
            "随机划分与 OOT 的差距不能发现泄漏，两者都被污染。"
        ),
        "abl": "删除后离线 OOT PR-AUC 变化",
        "fix_h": "处理建议",
        "fix": [
            "标签：为每个事件记录标签可用时间；训练截止日之后才成熟的标签一律视为未知，不是 0。",
            "划分：按时间切分，训练与测试之间留出成熟窗口；不要随机划分。",
            "评估：测试集只用成熟标签，或按成熟队列分别报告；同时报告对未成熟的敏感性。",
            "近期数据：用延迟分布做软标签校正，或加权，而不是直接丢弃或当成好样本。",
            "特征：每个特征登记“可用时间”，用 as-of 取数；上线前做 point-in-time 重算对账。",
            "监控：上线后跟踪各成熟度队列的坏账率与 PR-AUC，用于发现漂移与泄漏。",
        ],
        "caveat": "合成数据、单一数据种子；数值说明机制，不代表真实业务水平。",
    },
    "en": {
        "title": "Label maturity and future leakage",
        "intro": (
            "Purpose-built synthetic transactions ({n:,} events, {u:,} users, {d} days, "
            "{br:.1%} bad). A bad label appears only when the return arrives (median {p50:.0f} "
            "days, 95th percentile {p95:.0f}, like ACH returns). The same XGBoost settings are "
            "used throughout; only the training/evaluation method and features change. Day "
            "{cut:.0f} is the training cutoff and the next {td:.0f} days are the out-of-time test."
        ),
        "setup_h": "What is planted in the data",
        "setup": [
            (
                "Concept drift: the old pattern (large amounts, new device, failed logins) fades while "
                "a new one (night-time, state mismatch) emerges between days 100 and 180."
            ),
            (
                "Label delay: the new pattern is confirmed slowly (median 35 days), the old one "
                "quickly (median 8 days)."
            ),
            (
                "Leaky column fut_txn_cnt_30d: the user's transactions in the 30 days after the event "
                "(frozen fraud accounts go quiet)."
            ),
            (
                "Leaky column acct_closed_flag: an export-time account snapshot (closed if the user "
                "ever had a bad event)."
            ),
        ],
        "p1": "Part 1: label maturity and out-of-time testing",
        "delay_h": "Return delay (cumulative share)",
        "weekly_h": "Bad rate by event week: final vs observed at the cutoff",
        "weekly_note": (
            "Near the cutoff the observed bad rate drops because many bads have not returned yet "
            "and are read as good. Worse, the gaps are uneven: the slow-to-confirm new pattern is "
            "missing most, so the freshest data lacks the labels that matter most."
        ),
        "val_h": "Validation scheme: random split vs out-of-time",
        "val_cols": ["Scheme", "ROC-AUC", "PR-AUC", "Note"],
        "val_rand": "Random split (matured data)",
        "val_oot": "Out-of-time (30 days after cutoff)",
        "val_rand_n": "same period and pattern, inflated",
        "val_oot_n": "closer to production",
        "bias_h": "Evaluate on matured labels too",
        "bias_cols": ["Test labels", "Positives", "Bad rate", "PR-AUC"],
        "bias_final": "Final labels (wait for maturity)",
        "bias_imm": "Labels known when the test window ends (immature)",
        "sweep_h": "Training maturity window (embargo) vs OOT performance",
        "sweep_note": (
            "Training uses only events at least this many days before the cutoff; 0 means every "
            "known label. With drift, waiting makes labels more complete but data older, so "
            "waiting alone does not pay. The dashed line is delay correction (keep recent rows, "
            "replace unobserved zeros by soft labels from the delay distribution). Three model "
            "seeds are averaged; do not over-read small differences."
        ),
        "sweep_cols": [
            "Window (days)",
            "Train rows",
            "Train bad rate (known)",
            "(final)",
            "OOT ROC-AUC",
            "OOT PR-AUC",
        ],
        "corr": "Delay-corrected (soft labels)",
        "p2": "Part 2: future leakage",
        "leak_h": "One model, three ways to evaluate it",
        "leak_cols": [
            "Feature set",
            "Random-split PR-AUC",
            "OOT offline PR-AUC",
            "OOT serving (point-in-time) PR-AUC",
            "Serving ROC-AUC",
        ],
        "clean": "Clean features (7)",
        "leaky": "Clean + 2 leaky columns",
        "leak_note": (
            "Offline (history that includes the leaky columns) looks superb and OOT does not "
            "expose it, because the leaky columns also come from the future in the test period. "
            "Only recomputing with the values available at event time collapses it (PR-AUC below "
            "the base rate)."
        ),
        "pr_h": "ROC and PR curves: clean vs leaky (offline, serving)",
        "roc": "ROC curve",
        "pr": "PR curve",
        "base": "base rate",
        "c_clean": "Clean (serving)",
        "c_leak_off": "Leaky (offline)",
        "c_leak_srv": "Leaky (serving)",
        "det_h": "How to find the leak",
        "det_cols": [
            "Feature",
            "Univariate AUC",
            "Point-in-time recompute mismatch",
            "Importance in leaky model",
        ],
        "det_note": (
            "Three checks: (1) implausibly high univariate AUC; (2) recompute the feature from "
            "data before t and compare with the stored value, any mismatch means future "
            "information; (3) drop the feature and re-evaluate OOT, a large fall means the model "
            "relies on it. The random-vs-OOT gap does not reveal leakage because both are "
            "contaminated."
        ),
        "abl": "Offline OOT PR-AUC change when dropped",
        "fix_h": "What to do",
        "fix": [
            (
                "Labels: record when each label becomes available; labels maturing after the "
                "training cutoff are unknown, not zero."
            ),
            "Split: split by time with a maturity gap between train and test; never randomly.",
            (
                "Evaluation: use matured labels only, or report per maturity cohort, and show "
                "sensitivity to immature labels."
            ),
            (
                "Recent data: correct with the delay distribution (soft labels or weights) rather "
                "than dropping it or treating it as good."
            ),
            (
                "Features: register an availability time per feature, build as-of, and reconcile a "
                "point-in-time recompute before launch."
            ),
            (
                "Monitoring: track bad rate and PR-AUC per maturity cohort after launch to catch "
                "drift and leakage."
            ),
        ],
        "caveat": "Synthetic data, single data seed: numbers show the mechanism, not real-world levels.",
    },
}


def _table(head, rows):
    th = "".join(f"<th>{_esc(h)}</th>" for h in head)
    tr = "".join(
        "<tr>" + "".join(f'<td style="text-align:left">{c}</td>' for c in r) + "</tr>" for r in rows
    )
    return f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _pair(items, T):
    """ROC and PR curves side by side for [(name, color, scores)]; scores carry roc/pr curves."""
    roc = [
        {"name": n, "color": c, "xs": sc["roc"]["fpr"], "ys": sc["roc"]["tpr"]}
        for n, c, sc in items
    ]
    pr = [
        {"name": n, "color": c, "xs": sc["pr"]["recall"], "ys": sc["pr"]["precision"]}
        for n, c, sc in items
    ]
    legend = "".join(
        f'<span class="chip"><i style="background:{c}"></i>{_esc(n)}</span>' for n, c, _ in items
    )
    rates = ", ".join(f"{sc['base_rate']:.3f}" for _, _, sc in items)
    return (
        f'<div class="legend">{legend}</div><div class="grid">'
        f'<div class="card"><h3>{_esc(T["roc"])}</h3>'
        f"{svg_lines(roc, xlabel='FPR', ylabel='TPR', diagonal=True)}</div>"
        f'<div class="card"><h3>{_esc(T["pr"])}</h3>'
        f"{svg_lines(pr, xlabel='Recall', ylabel='Precision', baseline_y=items[0][2]['base_rate'])}"
        f'<p class="note">{_esc(T["base"])}: {rates}</p></div></div>'
    )


def render_temporal(r: dict, lang: str = "zh") -> str:
    T = _TXT.get(lang, _TXT["zh"])
    cfg, dl, dt = r["config"], r["delay"], r["data"]
    intro = T["intro"].format(
        n=dt["n"],
        u=dt["n_users"],
        d=dt["span_days"],
        br=dt["bad_rate"],
        p50=dl["p50"],
        p95=dl["p95"],
        cut=cfg["cutoff"],
        td=cfg["test_days"],
    )
    f3 = lambda v: f"{v:.3f}"
    delay_chart = _chart(
        [{"name": "cdf", "color": "#2f6fed", "xs": dl["cdf_x"], "ys": dl["cdf_y"]}],
        xmax=90,
        ymax=1.0,
        xlabel="days",
        ylabel="share",
        vlines=[(dl["p50"], "p50"), (dl["p95"], "p95")],
        pct=True,
    )
    w = r["weekly"]
    ymax = max(max(a[1], a[2]) for a in w) * 1.15
    weekly_chart = _chart(
        [
            {"name": "final", "color": "#2f6fed", "xs": [a[0] for a in w], "ys": [a[1] for a in w]},
            {
                "name": "observed",
                "color": "#e4572e",
                "xs": [a[0] for a in w],
                "ys": [a[2] for a in w],
            },
        ],
        xmax=cfg["cutoff"],
        ymax=ymax,
        xlabel="event day",
        ylabel="bad rate",
        pct=True,
    )
    sw = r["sweep"]
    ymax2 = max(max(s["pr_auc"] for s in sw), r["corrected"]["pr_auc"]) * 1.2
    sweep_chart = _chart(
        [
            {
                "name": "PR-AUC",
                "color": "#2f6fed",
                "xs": [s["embargo"] for s in sw],
                "ys": [s["pr_auc"] for s in sw],
                "dots": True,
            },
            {
                "name": T["corr"],
                "color": "#17a398",
                "xs": [0, sw[-1]["embargo"]],
                "ys": [r["corrected"]["pr_auc"]] * 2,
            },
        ],
        xmax=sw[-1]["embargo"],
        ymax=ymax2,
        xlabel=T["sweep_cols"][0],
        ylabel="OOT PR-AUC",
    )
    val = r["validation"]
    val_rows = [
        [
            T["val_rand"],
            f3(val["random_split"]["auc"]),
            f3(val["random_split"]["pr_auc"]),
            T["val_rand_n"],
        ],
        [T["val_oot"], f3(val["oot"]["auc"]), f3(val["oot"]["pr_auc"]), T["val_oot_n"]],
    ]
    eb = r["eval_bias"]
    bias_rows = [
        [
            T["bias_final"],
            f"{eb['final']['n_pos']:,}",
            f"{eb['final']['base_rate']:.4f}",
            f3(eb["final"]["pr_auc"]),
        ],
        [
            T["bias_imm"],
            f"{eb['immature']['n_pos']:,}",
            f"{eb['immature']['base_rate']:.4f}",
            f3(eb["immature"]["pr_auc"]),
        ],
    ]
    sweep_rows = [
        [
            str(s["embargo"]),
            f"{s['train_rows']:,}",
            f"{s['train_bad_rate_obs']:.4f}",
            f"{s['train_bad_rate_final']:.4f}",
            f3(s["auc"]),
            f3(s["pr_auc"]),
        ]
        for s in sw
    ]
    sweep_rows.append(
        [T["corr"], "—", "—", "—", f3(r["corrected"]["auc"]), f3(r["corrected"]["pr_auc"])]
    )
    lk = r["leak"]
    leak_rows = []
    for key, name in (("clean", T["clean"]), ("leaky", T["leaky"])):
        m = lk[key]
        leak_rows.append(
            [
                name,
                f3(m["random_split"]["pr_auc"]),
                f3(m["oot_offline"]["pr_auc"]),
                f3(m["oot_serving"]["pr_auc"]),
                f3(m["oot_serving"]["auc"]),
            ]
        )
    lk["clean"]["oot_serving"]["base_rate"]
    leak_pair = _pair(
        [
            (T["c_clean"], "#17a398", lk["clean"]["oot_serving"]),
            (T["c_leak_off"], "#e4572e", lk["leaky"]["oot_offline"]),
            (T["c_leak_srv"], "#6c757d", lk["leaky"]["oot_serving"]),
        ],
        T,
    )
    val_pair = _pair(
        [
            (T["val_rand"], "#8e44ad", val["random_split"]),
            (T["val_oot"], "#2f6fed", val["oot"]),
            (T["bias_imm"], "#f2a900", eb["immature"]),
        ],
        T,
    )
    sweep_pair = _pair(
        [
            (f"{T['sweep_cols'][0]} 0", "#e4572e", sw[0]),
            (f"{T['sweep_cols'][0]} {sw[-1]['embargo']}", "#6c757d", sw[-1]),
            (T["corr"], "#17a398", r["corrected"]),
        ],
        T,
    )
    imp = lk["leaky"]["importance"]
    det_rows = []
    for d in r["detect"]:
        det_rows.append(
            [
                f"<code>{_esc(d['feature'])}</code>",
                f3(d["uni_auc"]),
                f"{d['pit_mismatch']:.1%}",
                f"{imp.get(d['feature'], 0):.3f}",
            ]
        )
    abl = ", ".join(f"<code>{k}</code>: {v:+.3f}" for k, v in r["ablation"].items())

    def sec(h, body):
        return f"<section><h2>{_esc(h)}</h2>{body}</section>"

    p1 = (
        f'<div class="grid"><div class="card"><h3>{_esc(T["delay_h"])}</h3>{delay_chart}</div>'
        f'<div class="card"><h3>{_esc(T["weekly_h"])}</h3>{weekly_chart}'
        f'<p class="note">{_esc(T["weekly_note"])}</p></div></div>'
        f"<h3>{_esc(T['val_h'])}</h3>{_table(T['val_cols'], val_rows)}{val_pair}"
        f"<h3>{_esc(T['bias_h'])}</h3>{_table(T['bias_cols'], bias_rows)}"
        f'<h3>{_esc(T["sweep_h"])}</h3><p class="note">{_esc(T["sweep_note"])}</p>'
        f'<div class="card" style="max-width:640px">{sweep_chart}</div>{sweep_pair}'
        f"{_table(T['sweep_cols'], sweep_rows)}"
    )
    p2 = (
        f"<h3>{_esc(T['leak_h'])}</h3>{_table(T['leak_cols'], leak_rows)}"
        f'<p class="note">{_esc(T["leak_note"])}</p>'
        f"<h3>{_esc(T['pr_h'])}</h3>{leak_pair}"
        f"<h3>{_esc(T['det_h'])}</h3>{_table(T['det_cols'], det_rows)}"
        f'<p class="note">{_esc(T["det_note"])}</p><p class="note">{_esc(T["abl"])}: {abl}</p>'
    )
    fix = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in T["fix"]) + "</ul>"
    setup = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in T["setup"]) + "</ul>"
    return (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(T['title'])}</title><style>{_CSS}</style></head><body><main>"
        f'<header><h1>{_esc(T["title"])}</h1><div class="sub">{_esc(r["generated_at"])}</div>'
        f'<p class="note">{_esc(intro)}</p></header>'
        + sec(T["setup_h"], setup)
        + sec(T["p1"], p1)
        + sec(T["p2"], p2)
        + sec(T["fix_h"], fix + f'<p class="note">{_esc(T["caveat"])}</p>')
        + "</main></body></html>"
    )

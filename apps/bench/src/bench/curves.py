"""Curve-shape study: one XGBoost, several datasets/conditions, ROC and PR curves side by side.

Shows what PR/ROC curves look like under extreme class imbalance, with few positives or few
distinct scores (staircases), and with target leakage.
"""

import html as _html
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from xgboost import XGBClassifier

from bench.features import build_features, feature_names
from bench.models import train_all
from bench.report import _CSS, svg_lines
from bench.runner import load_events, time_split

_esc = _html.escape
COLORS = ["#2f6fed", "#e4572e", "#17a398", "#f2a900", "#8e44ad", "#6c757d"]
LEAK_FLIP = 0.03  # share of rows where the leaked label echo disagrees with the label


def _prepare(data_dir, *, leak: bool = False, seed: int = 0):
    """Time-split features of one dataset. With ``leak`` two leaky columns are added to each split."""
    events, _ = load_events(data_dir)
    feats = build_features(events)
    names = feature_names(feats)
    df = events.select("event_id", "event_time", "label").join(
        feats, on="event_id", how="left", maintain_order="left"
    )
    if leak:
        rng = np.random.default_rng(seed)
        y = df["label"].to_numpy().astype(int)
        flip = rng.random(len(y)) < LEAK_FLIP
        golden = pl.read_parquet(Path(data_dir) / "golden.parquet", columns=["event_id", "score"])
        df = df.with_columns(
            leak_label_echo=pl.Series(np.where(flip, 1 - y, y)),
        ).join(golden.rename({"score": "leak_golden_score"}), on="event_id", how="left")
    tr, va, te = time_split(df)
    return tr, va, te, names


def _xy(frame, cols):
    return frame.select(cols).to_numpy().astype("float64"), frame["label"].to_numpy().astype(int)


def _fit_xgb(tr, va, cols, seed):
    xt, yt = _xy(tr, cols)
    xv, yv = _xy(va, cols)
    m = train_all(xt, yt, xv, yv, names=("xgb",), seed=seed)["xgb"]
    if not hasattr(m, "predict_proba"):
        raise RuntimeError(m.error)
    return m


def _curves(y, p) -> dict:
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    return {
        "fpr": fpr.tolist(),
        "tpr": tpr.tolist(),
        "recall": rec.tolist(),
        "precision": prec.tolist(),
        "auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "n": len(y),
        "n_pos": int(y.sum()),
        "base_rate": float(y.mean()),
        "n_distinct": len(np.unique(p)),
    }


def run_curves(base_dir, rare_dir, *, seed: int = 0, verbose: bool = False) -> dict:
    def log(msg):
        if verbose:
            print(msg, flush=True)

    out = {}
    tr, va, te, names = _prepare(base_dir, leak=True, seed=seed)
    model = _fit_xgb(tr, va, names, seed)
    xte, yte = _xy(te, names)
    p = model.predict_proba(xte)
    out["base"] = _curves(yte, p)
    log(f"base: auc={out['base']['auc']:.3f} pr={out['base']['pr_auc']:.3f}")

    rng = np.random.default_rng(seed)
    for key, n in (("sample_1000", 1000), ("sample_250", 250)):
        idx = rng.choice(len(yte), n, replace=False)
        out[key] = _curves(yte[idx], p[idx])

    xt, yt = _xy(tr, names)
    coarse = XGBClassifier(
        n_estimators=3, max_depth=1, learning_rate=0.3, tree_method="hist", random_state=seed
    ).fit(xt, yt)
    out["coarse"] = _curves(yte, coarse.predict_proba(xte)[:, 1])

    for key, extra in (
        ("leak_echo", ["leak_label_echo"]),
        ("leak_score", ["leak_golden_score"]),
    ):
        m = _fit_xgb(tr, va, names + extra, seed)
        x, y = _xy(te, names + extra)
        out[key] = _curves(y, m.predict_proba(x))
        log(f"{key}: auc={out[key]['auc']:.3f} pr={out[key]['pr_auc']:.3f}")

    tr, va, te, names = _prepare(rare_dir)
    m = _fit_xgb(tr, va, names, seed)
    x, y = _xy(te, names)
    out["rare"] = _curves(y, m.predict_proba(x))
    out["rare"]["train_pos"] = int(tr["label"].sum())
    log(f"rare: auc={out['rare']['auc']:.3f} pr={out['rare']['pr_auc']:.3f}")
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "base_dir": str(base_dir),
        "rare_dir": str(rare_dir),
        "scenarios": out,
    }


def _pr_step(c):
    """PR curve as the right-continuous step function that average precision integrates."""
    r, p = np.array(c["recall"])[::-1], np.array(c["precision"])[::-1]  # recall ascending
    xs, ys = [float(r[0])], [float(p[0])]
    for k in range(1, len(r)):
        xs += [float(r[k - 1]), float(r[k])]
        ys += [float(p[k]), float(p[k])]
    return xs, ys


def _roc_step(c):
    """ROC points joined by straight lines (what ROC-AUC integrates): ties show as diagonals."""
    return c["fpr"], c["tpr"]


_TXT = {
    "zh": {
        "title": "PR / ROC 曲线形状实验",
        "intro": (
            "同一个 XGBoost（参数不变），只改变数据或评估条件，观察 ROC 与 PR 曲线怎样变化。"
            "基础数据为 50 万笔合成支付交易（坏账率约 2%）。"
        ),
        "scen": {
            "base": "基线 (坏账率 2%)",
            "rare": "极度不平衡 (坏账率 0.1%)",
            "sample_1000": "测试集仅 1000 行",
            "sample_250": "测试集仅 250 行",
            "coarse": "模型太粗 (3 棵深度 1 的树)",
            "leak_echo": "泄漏：标签回声列",
            "leak_score": "泄漏：真实概率（噪声上限）",
        },
        "g1": "1. 标签极度不平衡",
        "g1_note": (
            "虚线是随机分类器的水平线，高度等于坏账率，坏账率越低它越贴近 0。FPR 以海量负样本为分母，"
            "几个误报几乎不改变 FPR，所以 ROC 曲线显得很漂亮（这里 ROC-AUC 高达 0.998）；"
            "PR 曲线的精确率直接受每个误报影响，PR-AUC 只有约 0.52，才反映真实难度。"
            "极度不平衡时应以 PR-AUC 和固定精确率下的召回为准。"
        ),
        "g2": "2. 阶梯状曲线",
        "g2_note": (
            "阶梯来自两种情形：一是正样本很少，每多召回一个正样本曲线就跳一格，PR 曲线在两次"
            "召回之间随负样本增多而下滑，形成锯齿；二是模型输出的不同分数很少（树太少或太浅），"
            "大量样本同分，ROC 在同分处走直线、PR 出现大台阶。测试集越小、正样本越少，台阶越明显。"
        ),
        "g3": "3. 数据泄漏",
        "g3_note": (
            "“标签回声列”模拟事后才会产生的字段（如退款标记，仅 3% 与标签不一致）：预测时刻拿不到，"
            "训练时却被当成特征，ROC-AUC 升到 0.986、PR-AUC 升到 0.74，曲线贴紧左上角。"
            "“真实概率”是生成标签用的概率：标签是按它抽样的，即使完全知道它，也只能把 AUC 抬到"
            "噪声上限（约 0.79），所以这种“泄漏”几乎看不出来。泄漏越贴近标签本身，曲线越夸张。"
            "排查线索：单个特征重要度极高、指标远好于同类业务、上线后骤降。"
        ),
        "tbl": [
            "场景",
            "测试行数",
            "正样本",
            "坏账率",
            "ROC-AUC",
            "PR-AUC",
            "PR-AUC/基线",
            "不同分数数",
        ],
        "roc": "ROC 曲线",
        "pr": "PR 曲线（阶梯）",
        "base": "基线",
    },
    "en": {
        "title": "PR / ROC curve shapes",
        "intro": (
            "One XGBoost with fixed parameters; only the data or the evaluation condition "
            "changes, to show how ROC and PR curves respond. The base data is 500k synthetic "
            "payment transactions (about 2% bad)."
        ),
        "scen": {
            "base": "Baseline (2% bad)",
            "rare": "Extreme imbalance (0.1% bad)",
            "sample_1000": "Test set of 1,000 rows",
            "sample_250": "Test set of 250 rows",
            "coarse": "Coarse model (3 depth-1 trees)",
            "leak_echo": "Leak: label echo column",
            "leak_score": "Leak: true probability (noise ceiling)",
        },
        "g1": "1. Extreme label imbalance",
        "g1_note": (
            "The dashed line is a random classifier and sits at the bad rate, closer to zero the "
            "rarer the positives. FPR divides by a huge pool of negatives, so a handful of false "
            "alarms barely moves it and ROC looks superb (ROC-AUC 0.998 here), while precision "
            "feels every false alarm and PR-AUC is only about 0.52. Under extreme imbalance "
            "trust PR-AUC and recall at fixed precision."
        ),
        "g2": "2. Staircase curves",
        "g2_note": (
            "Stairs come from two situations. With few positives, each recalled positive is a "
            "jump, and precision sags between jumps as negatives accumulate, giving a sawtooth. "
            "With few distinct scores (too few or too shallow trees) many rows tie, so ROC "
            "runs straight lines across ties and PR shows large steps. The smaller the test set "
            "and the fewer the positives, the coarser the stairs."
        ),
        "g3": "3. Data leakage",
        "g3_note": (
            "The label echo column mimics a field that only exists after the outcome (such as "
            "a refund flag, 3% disagreeing with the label). It is unavailable at prediction time "
            "but used as a feature here, so ROC-AUC jumps to 0.986, PR-AUC to 0.74 and the "
            "curves hug the corner. The true probability is what labels were sampled from: even "
            "knowing it exactly only lifts AUC to the noise ceiling (about 0.79), so that "
            "leak is almost invisible. The closer a leak is to the label itself, the more "
            "dramatic the curve. Clues: one feature dominates importance, metrics far above "
            "comparable problems, a sharp drop after launch."
        ),
        "tbl": [
            "Scenario",
            "Test rows",
            "Positives",
            "Bad rate",
            "ROC-AUC",
            "PR-AUC",
            "PR-AUC / base",
            "Distinct scores",
        ],
        "roc": "ROC curve",
        "pr": "PR curve (steps)",
        "base": "baseline",
    },
}


def _panel(keys, scen, T, colors):
    roc, pr = [], []
    for k in keys:
        c = scen[k]
        col = colors[k]
        x, y = _roc_step(c)
        roc.append({"name": T["scen"][k], "color": col, "xs": x, "ys": y})
        x, y = _pr_step(c)
        pr.append({"name": T["scen"][k], "color": col, "xs": x, "ys": y})
    legend = "".join(
        f'<span class="chip"><i style="background:{colors[k]}"></i>{_esc(T["scen"][k])}</span>'
        for k in keys
    )
    rates = ", ".join(f"{scen[k]['base_rate']:.4f}" for k in keys)
    return (
        f'<div class="legend">{legend}</div><div class="grid">'
        f'<div class="card"><h3>{_esc(T["roc"])}</h3>'
        f"{svg_lines(roc, xlabel='FPR', ylabel='TPR', diagonal=True)}</div>"
        f'<div class="card"><h3>{_esc(T["pr"])}</h3>'
        f"{svg_lines(pr, xlabel='Recall', ylabel='Precision', baseline_y=scen[keys[-1]]['base_rate'])}"
        f'<p class="note">{_esc(T["base"])}: {rates}</p></div></div>'
    )


def render_curves(results: dict, lang: str = "zh") -> str:
    T = _TXT.get(lang, _TXT["zh"])
    s = results["scenarios"]
    colors = {k: COLORS[i % len(COLORS)] for i, k in enumerate(T["scen"])}
    groups = [
        ("g1", ["base", "rare"]),
        ("g2", ["base", "sample_1000", "sample_250", "coarse"]),
        ("g3", ["base", "leak_echo", "leak_score"]),
    ]
    sections = []
    for g, keys in groups:
        sections.append(
            f'<section><h2>{_esc(T[g])}</h2><p class="note">{_esc(T[g + "_note"])}</p>'
            f"{_panel(keys, s, T, colors)}</section>"
        )
    rows = ""
    for k in T["scen"]:
        c = s[k]
        lift = c["pr_auc"] / c["base_rate"] if c["base_rate"] else float("nan")
        cells = [
            _esc(T["scen"][k]),
            f"{c['n']:,}",
            f"{c['n_pos']:,}",
            f"{c['base_rate']:.4f}",
            f"{c['auc']:.3f}",
            f"{c['pr_auc']:.3f}",
            f"{lift:.1f}x",
            f"{c['n_distinct']:,}",
        ]
        rows += "<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>"
    head = "".join(f"<th>{_esc(h)}</th>" for h in T["tbl"])
    table = (
        f'<section><div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div></section>"
    )
    return (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(T['title'])}</title><style>{_CSS}</style></head><body><main>"
        f"<header><h1>{_esc(T['title'])}</h1>"
        f'<div class="sub">{_esc(results.get("generated_at", ""))}</div>'
        f'<p class="note">{_esc(T["intro"])}</p></header>{table}{"".join(sections)}'
        "</main></body></html>"
    )

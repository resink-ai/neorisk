"""Self-contained HTML comparison report (inline CSS + SVG, no network, no files)."""

import html as _html
import math

PALETTE = ["#2f6fed", "#e4572e", "#17a398", "#f2a900", "#8e44ad"]

_esc = _html.escape


def to_jsonable(obj):
    """Recursively convert numpy types to Python; any non-finite float becomes None."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None
    if np is not None:
        if isinstance(obj, np.ndarray):
            return to_jsonable(obj.tolist())
        if isinstance(obj, np.generic):
            return to_jsonable(obj.item())
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _fmt(v, digits: int = 3) -> str:
    f = _num(v)
    return "—" if f is None else f"{f:.{digits}f}"


def _fmt_int(v) -> str:
    f = _num(v)
    return "—" if f is None else f"{round(f):,}"


LABELS = {
    "zh": {
        "title": "模型对比报告",
        "summary": "汇总",
        "roc": "ROC 曲线",
        "pr": "PR 曲线",
        "metrics": "指标",
        "operating": "工作点",
        "calibration": "校准",
        "shap": "SHAP 特征贡献",
        "details": "运行详情",
        "failed": "失败的模型",
        "model": "模型",
        "best": "加粗为每列最优",
        "heat_note": "颜色越深越好（按列归一化）",
        "baseline": "正例率基线",
        "ideal": "完美校准",
        "threshold": "阈值",
        "shap_cross": "跨模型归一化重要性（各模型 top 8 的并集）",
        "shap_unavail": "SHAP 不可用",
        "shap_bars": "归一化重要性 (top 12)",
        "shap_strip": "SHAP 值分布（点颜色：特征值 低 → 高；横线：P25-P75，刻度：中位数）",
        "feature": "特征",
        "train_s": "训练 s",
        "infer_s": "推理 s",
        "shap_s": "SHAP s",
        "stages": "阶段耗时 (特征 / 全部训练 / 总计)",
        "data_dir": "数据目录",
        "n_events": "事件数",
        "n_features": "特征数",
        "splits": "划分 (train / valid / test)",
        "bad_rate": "坏账率",
        "seed": "随机种子",
        "generated": "生成时间",
        "features": "特征列表",
        "timings": "耗时与训练信息",
        "epochs": "训练轮数",
        "method": "解释方法",
        "rows": "解释行数",
        "no_models": "没有可展示的模型结果。",
        "pred_mean": "平均预测概率",
        "frac_pos": "实际正例比例",
    },
    "en": {
        "title": "Model comparison report",
        "summary": "Summary",
        "roc": "ROC curves",
        "pr": "PR curves",
        "metrics": "Metrics",
        "operating": "Operating point",
        "calibration": "Calibration",
        "shap": "SHAP",
        "details": "Run details",
        "failed": "Failed models",
        "model": "Model",
        "best": "Best value per column in bold",
        "heat_note": "Darker is better (min-max per column)",
        "baseline": "Positive-rate baseline",
        "ideal": "Perfect calibration",
        "threshold": "Threshold",
        "shap_cross": "Cross-model normalised importance (union of each model's top 8)",
        "shap_unavail": "SHAP unavailable",
        "shap_bars": "Normalised importance (top 12)",
        "shap_strip": (
            "SHAP value distribution (dot colour: feature value low to high; "
            "line: P25-P75, tick: median)"
        ),
        "feature": "Feature",
        "train_s": "Train s",
        "infer_s": "Infer s",
        "shap_s": "SHAP s",
        "stages": "Stage seconds (features / all training / total)",
        "data_dir": "Data dir",
        "n_events": "Events",
        "n_features": "Features",
        "splits": "Split sizes (train / valid / test)",
        "bad_rate": "Bad rate",
        "seed": "Seed",
        "generated": "Generated",
        "features": "Feature list",
        "timings": "Timings and training info",
        "epochs": "Epochs",
        "method": "Explainer",
        "rows": "Rows explained",
        "no_models": "No model results to show.",
        "pred_mean": "Mean predicted probability",
        "frac_pos": "Observed positive fraction",
    },
}

# (key, header, higher_is_better, digits)
_SUMMARY_COLS = [
    ("auc", "AUC", True, 3),
    ("pr_auc", "PR-AUC", True, 3),
    ("ks", "KS", True, 3),
    ("recall_at_p50", "recall@P0.5", True, 3),
    ("recall_at_p80", "recall@P0.8", True, 3),
    ("precision_top_1pct", "P@top1%", True, 3),
    ("lift_top_1pct", "lift@1%", True, 2),
    ("log_loss", "log loss", False, 4),
    ("brier", "Brier", False, 4),
]
_HEAT_KEYS = _SUMMARY_COLS + [("precision_top_0_5pct", "P@top0.5%", True, 3)]

_CSS = """
:root{--bg:#fafaf8;--fg:#1c1e21;--muted:#62666d;--card:#fff;--line:#d9dbe0;--grid:#e6e8ec;
--accent:#2f6fed;--warn-bg:#fff4e0;--warn-line:#e0a030;--best:#e6f4ea;--bar:#2f6fed}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14161a;--fg:#e8eaed;
--muted:#9aa0a8;--card:#1c1f24;--line:#3a3f47;--grid:#2a2e35;--accent:#7aa2ff;
--warn-bg:#3a2c12;--warn-line:#b8862b;--best:#1d3a27;--bar:#7aa2ff}}
:root[data-theme="dark"]{--bg:#14161a;--fg:#e8eaed;--muted:#9aa0a8;--card:#1c1f24;
--line:#3a3f47;--grid:#2a2e35;--accent:#7aa2ff;--warn-bg:#3a2c12;--warn-line:#b8862b;
--best:#1d3a27;--bar:#7aa2ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,
"Segoe UI","PingFang SC","Noto Sans SC",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}
h2{font-size:1.2rem;margin:40px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:1rem;margin:20px 0 8px}
.sub,.note{color:var(--muted);font-size:.85rem}
.facts{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.fact{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px}
.fact b{display:block;font-size:1.05rem}
.fact span{color:var(--muted);font-size:.78rem}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 4px}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--card);
border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:.85rem}
.chip i{display:inline-block;width:12px;height:12px;border-radius:50%}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;
min-width:0}
.card h3{margin-top:0}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);
border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:.88rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{color:var(--muted);font-weight:600;font-size:.78rem}
tr:last-child td{border-bottom:0}
td.best{background:var(--best);font-weight:700}
td.heat{color:#0b1220;text-align:center}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.callout{border-radius:8px;padding:10px 14px;margin:12px 0;border:1px solid var(--line)}
.callout.warn{background:var(--warn-bg);border-color:var(--warn-line)}
.callout ul{margin:6px 0 0;padding-left:20px}
.pillbar{display:flex;align-items:center;gap:8px}
.pillbar .b{height:8px;border-radius:4px;background:var(--bar);min-width:1px}
.pillbar span{font-size:.8rem;color:var(--muted)}
svg.chart{width:100%;height:auto;display:block}
svg text{fill:var(--fg);font-size:11px;font-family:inherit}
code{font-size:.82rem;background:var(--grid);padding:1px 5px;border-radius:4px}
@media (max-width:560px){main{padding:16px 16px 48px}h1{font-size:1.3rem}}
"""


def _fx(v: float) -> str:
    return f"{v:.2f}"


def svg_lines(
    series,
    *,
    xlabel,
    ylabel,
    diagonal=False,
    baseline_y=None,
    width=520,
    height=360,
) -> str:
    """Line chart on [0,1]x[0,1]. series: [{"name","color","xs","ys"}]."""
    ml, mr, mt, mb = 52, 14, 14, 46
    pw, ph = width - ml - mr, height - mt - mb

    def px(x):
        return ml + min(max(x, 0.0), 1.0) * pw

    def py(y):
        return mt + (1 - min(max(y, 0.0), 1.0)) * ph

    out = [
        (
            f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{_esc(str(ylabel))} vs {_esc(str(xlabel))}">'
        )
    ]
    for i in range(6):
        t = i / 5
        out.append(
            f'<line x1="{_fx(px(t))}" y1="{mt}" x2="{_fx(px(t))}" y2="{mt + ph}" '
            'stroke="var(--grid)" stroke-width="1"/>'
        )
        out.append(
            f'<line x1="{ml}" y1="{_fx(py(t))}" x2="{ml + pw}" y2="{_fx(py(t))}" '
            'stroke="var(--grid)" stroke-width="1"/>'
        )
        out.append(f'<text x="{_fx(px(t))}" y="{mt + ph + 16}" text-anchor="middle">{t:.1f}</text>')
        out.append(f'<text x="{ml - 8}" y="{_fx(py(t) + 4)}" text-anchor="end">{t:.1f}</text>')
    out.append(
        f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="none" '
        'stroke="var(--line)" stroke-width="1"/>'
    )
    if diagonal:
        out.append(
            f'<line x1="{_fx(px(0))}" y1="{_fx(py(0))}" x2="{_fx(px(1))}" y2="{_fx(py(1))}" '
            'stroke="var(--muted)" stroke-width="1" stroke-dasharray="5 4"/>'
        )
    by = _num(baseline_y)
    if by is not None:
        out.append(
            f'<line x1="{ml}" y1="{_fx(py(by))}" x2="{ml + pw}" y2="{_fx(py(by))}" '
            'stroke="var(--muted)" stroke-width="1" stroke-dasharray="5 4"/>'
        )
    for s in series:
        pts = []
        for x, y in zip(s.get("xs", []), s.get("ys", []), strict=False):
            fx, fy = _num(x), _num(y)
            if fx is not None and fy is not None:
                pts.append(f"{_fx(px(fx))},{_fx(py(fy))}")
        if pts:
            out.append(
                f'<polyline points="{" ".join(pts)}" fill="none" '
                f'stroke="{_esc(str(s.get("color", "#2f6fed")))}" stroke-width="2" '
                'stroke-linejoin="round" stroke-linecap="round">'
                f"<title>{_esc(str(s.get('name', '')))}</title></polyline>"
            )
    out.append(
        f'<text x="{ml + pw / 2}" y="{height - 8}" text-anchor="middle">{_esc(str(xlabel))}</text>'
    )
    out.append(
        f'<text transform="translate(14 {mt + ph / 2}) rotate(-90)" text-anchor="middle">'
        f"{_esc(str(ylabel))}</text>"
    )
    out.append("</svg>")
    return "".join(out)


def _legend(models) -> str:
    chips = "".join(
        f'<span class="chip"><i style="background:{m["color"]}"></i>{_esc(m["display"])}</span>'
        for m in models
    )
    return f'<div class="legend">{chips}</div>'


def _best_flags(models, key, higher):
    vals = [_num((m["metrics"] or {}).get(key)) for m in models]
    finite = [v for v in vals if v is not None]
    if not finite:
        return [False] * len(models)
    target = max(finite) if higher else min(finite)
    return [v is not None and v == target for v in vals]


def _summary_table(models, L) -> str:
    cols = _SUMMARY_COLS
    head = "".join(f"<th>{_esc(h)}</th>" for _, h, _, _ in cols)
    head += f"<th>{_esc(L['train_s'])}</th><th>{_esc(L['infer_s'])}</th>"
    flags = {k: _best_flags(models, k, hi) for k, _, hi, _ in cols}
    tflags = {}
    for k in ("train_seconds", "infer_seconds"):
        vals = [_num(m.get(k)) for m in models]
        fin = [v for v in vals if v is not None]
        t = min(fin) if fin else None
        tflags[k] = [v is not None and v == t for v in vals]
    rows = []
    for i, m in enumerate(models):
        cells = [
            (
                f'<td><span class="dot" style="background:{m["color"]}"></span>'
                f"{_esc(m['display'])}</td>"
            )
        ]
        for k, _, _, d in cols:
            cls = ' class="best"' if flags[k][i] else ""
            cells.append(f"<td{cls}>{_fmt((m['metrics'] or {}).get(k), d)}</td>")
        for k in ("train_seconds", "infer_seconds"):
            cls = ' class="best"' if tflags[k][i] else ""
            cells.append(f"<td{cls}>{_fmt(m.get(k), 2)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="tablewrap"><table><thead><tr>'
        f"<th>{_esc(L['model'])}</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f'</table></div><p class="note">{_esc(L["best"])}</p>'
    )


def _heatmap(models, L) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for _, h, _, _ in _HEAT_KEYS)
    ranges = {}
    for k, _, _, _ in _HEAT_KEYS:
        vals = [_num((m["metrics"] or {}).get(k)) for m in models]
        fin = [v for v in vals if v is not None]
        ranges[k] = (min(fin), max(fin)) if fin else None
    rows = []
    for m in models:
        cells = [
            (
                f'<td><span class="dot" style="background:{m["color"]}"></span>'
                f"{_esc(m['display'])}</td>"
            )
        ]
        for k, _, hi, d in _HEAT_KEYS:
            v = _num((m["metrics"] or {}).get(k))
            r = ranges[k]
            if v is None or r is None:
                cells.append("<td>—</td>")
                continue
            lo, hi_v = r
            t = 0.5 if hi_v == lo else (v - lo) / (hi_v - lo)
            if not hi:
                t = 1 - t
            light = 92 - 42 * t  # darker = better
            cells.append(
                f'<td class="heat" style="background:hsl(210 70% {light:.0f}%)'
                f'{";color:#fff" if light < 62 else ""}">{_fmt(v, d)}</td>'
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="tablewrap"><table><thead><tr>'
        f"<th>{_esc(L['model'])}</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f'</table></div><p class="note">{_esc(L["heat_note"])}</p>'
    )


def _confusion_table(models, L) -> str:
    rows = []
    for m in models:
        c = (m["metrics"] or {}).get("confusion")
        name = (
            f'<td><span class="dot" style="background:{m["color"]}"></span>'
            f"{_esc(m['display'])}</td>"
        )
        if not c:
            rows.append(f"<tr>{name}{'<td>—</td>' * 8}</tr>")
            continue
        rows.append(
            f"<tr>{name}<td>{_fmt(c.get('threshold'), 4)}</td>"
            + "".join(f"<td>{_fmt_int(c.get(k))}</td>" for k in ("tp", "fp", "fn", "tn"))
            + "".join(f"<td>{_fmt(c.get(k), 3)}</td>" for k in ("precision", "recall", "f1"))
            + "</tr>"
        )
    heads = [L["threshold"], "TP", "FP", "FN", "TN", "Precision", "Recall", "F1"]
    return (
        '<div class="tablewrap"><table><thead><tr>'
        f"<th>{_esc(L['model'])}</th>{''.join(f'<th>{_esc(h)}</th>' for h in heads)}"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _curve_series(models, curve_key, xk, yk):
    out = []
    for m in models:
        c = (m["metrics"] or {}).get(curve_key) or {}
        out.append(
            {"name": m["display"], "color": m["color"], "xs": c.get(xk, []), "ys": c.get(yk, [])}
        )
    return out


def _calibration_svg(models, L) -> str:
    series = []
    for m in models:
        cal = (m["metrics"] or {}).get("calibration") or []
        series.append(
            {
                "name": m["display"],
                "color": m["color"],
                "xs": [b.get("mean_pred") for b in cal],
                "ys": [b.get("frac_pos") for b in cal],
            }
        )
    return svg_lines(series, xlabel=L["pred_mean"], ylabel=L["frac_pos"], diagonal=True)


def _norm_importance(shap) -> dict[str, float]:
    imp = {k: _num(v) or 0.0 for k, v in ((shap or {}).get("importance") or {}).items()}
    tot = sum(imp.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in imp.items()}


def _bar_svg(items, color, width=520) -> str:
    """Horizontal bars; items: [(name, frac)]."""
    if not items:
        return ""
    row_h, ml, mr = 22, 150, 56
    h = row_h * len(items) + 8
    mx = max(v for _, v in items) or 1.0
    pw = width - ml - mr
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img">']
    for i, (name, v) in enumerate(items):
        y = 4 + i * row_h
        w = max(1.0, pw * v / mx)
        label = name if len(name) <= 24 else name[:23] + "…"
        out.append(
            f'<text x="{ml - 8}" y="{y + 15}" text-anchor="end">{_esc(label)}'
            f"<title>{_esc(name)}</title></text>"
            f'<rect x="{ml}" y="{y + 3}" width="{w:.1f}" height="14" rx="3" fill="{color}"/>'
            f'<text x="{ml + w + 6:.1f}" y="{y + 15}">{v * 100:.1f}%</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _value_color(t: float) -> str:
    t = min(max(t, 0.0), 1.0)
    hue = 215 - 215 * t  # blue (215) -> red (0)
    return f"hsl({hue:.0f} 75% 52%)"


def _strip_svg(shap, feats, width=520) -> str:
    row_h, ml, mr, mt, mb = 26, 150, 14, 6, 26
    pts = shap.get("points") or {}
    quants = shap.get("quantiles") or {}
    allv = []
    for f in feats:
        allv += [v for v in (_num(x) for x in (pts.get(f) or {}).get("shap", [])) if v is not None]
        allv += [v for v in (_num(x) for x in quants.get(f, [])) if v is not None]
    if not allv:
        return ""
    lo, hi = min(allv), max(allv)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pw = width - ml - mr
    h = mt + row_h * len(feats) + mb

    def X(v):
        return ml + (v - lo) / (hi - lo) * pw

    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img">']
    if lo < 0 < hi:
        out.append(
            f'<line x1="{X(0):.1f}" y1="{mt}" x2="{X(0):.1f}" y2="{h - mb}" '
            'stroke="var(--muted)" stroke-dasharray="3 3"/>'
        )
    for i, f in enumerate(feats):
        cy = mt + i * row_h + row_h / 2
        label = f if len(f) <= 24 else f[:23] + "…"
        out.append(f'<text x="{ml - 8}" y="{cy + 4:.1f}" text-anchor="end">{_esc(label)}</text>')
        q = [_num(x) for x in quants.get(f, [])]
        if len(q) >= 4 and q[1] is not None and q[3] is not None:
            out.append(
                f'<line x1="{X(q[1]):.1f}" y1="{cy:.1f}" x2="{X(q[3]):.1f}" y2="{cy:.1f}" '
                'stroke="var(--fg)" stroke-width="3" stroke-opacity=".35" stroke-linecap="round"/>'
            )
        if len(q) >= 3 and q[2] is not None:
            out.append(
                f'<line x1="{X(q[2]):.1f}" y1="{cy - 7:.1f}" x2="{X(q[2]):.1f}" '
                f'y2="{cy + 7:.1f}" stroke="var(--fg)" stroke-width="2"/>'
            )
        p = pts.get(f) or {}
        for sv, val in zip(p.get("shap", []), p.get("value", []), strict=False):
            a, b = _num(sv), _num(val)
            if a is None:
                continue
            out.append(
                f'<circle cx="{X(a):.1f}" cy="{cy:.1f}" r="2.4" '
                f'fill="{_value_color(b if b is not None else 0.5)}" fill-opacity=".7"/>'
            )
    for t in (lo, (lo + hi) / 2, hi):
        out.append(f'<text x="{X(t):.1f}" y="{h - 8}" text-anchor="middle">{t:.3g}</text>')
    out.append("</svg>")
    return "".join(out)


def _shap_section(models, L) -> str:
    have = [m for m in models if m.get("shap")]
    parts = []
    if have:
        norms = {m["key"]: _norm_importance(m["shap"]) for m in have}
        union: list[str] = []
        for m in have:
            top = sorted(norms[m["key"]].items(), key=lambda kv: -kv[1])[:8]
            for f, _ in top:
                if f not in union:
                    union.append(f)
        union.sort(key=lambda f: -max(norms[m["key"]].get(f, 0.0) for m in have))
        mx = max((norms[m["key"]].get(f, 0.0) for m in have for f in union), default=0) or 1.0
        head = "".join(f"<th>{_esc(m['display'])}</th>" for m in have)
        rows = []
        for f in union:
            cells = []
            for m in have:
                v = norms[m["key"]].get(f, 0.0)
                w = 100 * v / mx
                cells.append(
                    '<td><div class="pillbar" style="justify-content:flex-end">'
                    f'<div class="b" style="width:{w * 0.6:.0f}px;background:{m["color"]}"></div>'
                    f"<span>{v * 100:.1f}%</span></div></td>"
                )
            rows.append(f"<tr><td>{_esc(f)}</td>{''.join(cells)}</tr>")
        parts.append(
            f"<h3>{_esc(L['shap_cross'])}</h3>"
            '<div class="tablewrap"><table><thead><tr>'
            f"<th>{_esc(L['feature'])}</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
            "</table></div>"
        )
    cards = []
    for m in models:
        s = m.get("shap")
        title = (
            f'<h3><span class="dot" style="background:{m["color"]}"></span>'
            f"{_esc(m['display'])}</h3>"
        )
        if not s:
            cards.append(
                f'<div class="card">{title}<p class="note">{_esc(L["shap_unavail"])}</p></div>'
            )
            continue
        norm = _norm_importance(s)
        top = sorted(norm.items(), key=lambda kv: -kv[1])[:12]
        info = (
            f'<p class="note">{_esc(L["method"])}: {_esc(str(s.get("method", "")))} · '
            f"{_esc(L['rows'])}: {_fmt_int(s.get('n_rows'))}</p>"
        )
        cards.append(
            f'<div class="card">{title}{info}'
            f'<p class="note">{_esc(L["shap_bars"])}</p>{_bar_svg(top, m["color"])}'
            f'<p class="note">{_esc(L["shap_strip"])}</p>'
            f"{_strip_svg(s, [f for f, _ in top])}</div>"
        )
    parts.append(f'<div class="grid">{"".join(cards)}</div>')
    return "".join(parts)


def _facts(run, L) -> str:
    sp = run.get("split_sizes") or {}
    items = [
        (L["n_events"], _fmt_int(run.get("n_events"))),
        (L["n_features"], _fmt_int(run.get("n_features"))),
        (
            L["bad_rate"],
            _fmt(_pct(run.get("bad_rate")), 2) + "%"
            if _num(run.get("bad_rate")) is not None
            else "—",
        ),
        (
            L["splits"],
            " / ".join(_fmt_int(sp.get(k)) for k in ("train", "valid", "test")),
        ),
        (L["seed"], _esc(str(run.get("seed", "—")))),
    ]
    return (
        '<div class="facts">'
        + "".join(f'<div class="fact"><b>{v}</b><span>{_esc(k)}</span></div>' for k, v in items)
        + "</div>"
    )


def _pct(v):
    f = _num(v)
    return None if f is None else f * 100


def _details(run, models, L) -> str:
    rows = [
        (L["data_dir"], f"<code>{_esc(str(run.get('data_dir', '')))}</code>"),
        (L["generated"], _esc(str(run.get("generated_at", "")))),
        (L["n_events"], _fmt_int(run.get("n_events"))),
        (
            L["splits"],
            " / ".join(
                _fmt_int((run.get("split_sizes") or {}).get(k)) for k in ("train", "valid", "test")
            ),
        ),
        (L["bad_rate"], f"{_fmt(_pct(run.get('bad_rate')), 3)}%"),
        (L["seed"], _esc(str(run.get("seed", "")))),
        *(
            [
                (
                    L["stages"],
                    " / ".join(
                        _fmt(run["timings"].get(k), 1)
                        for k in ("feature_seconds", "train_all_seconds", "total_seconds")
                    ),
                )
            ]
            if isinstance(run.get("timings"), dict)
            else []
        ),
        (
            f"{L['features']} ({_fmt_int(run.get('n_features'))})",
            " ".join(f"<code>{_esc(str(f))}</code>" for f in run.get("feature_names") or []),
        ),
    ]
    kv = "".join(
        f'<tr><td>{_esc(k)}</td><td style="text-align:left;white-space:normal">{v}</td></tr>'
        for k, v in rows
    )
    trs = []
    for m in models:
        ep = m.get("epochs")
        trs.append(
            f"<tr><td>{_esc(m['display'])}</td><td>{_fmt(m.get('train_seconds'), 2)}</td>"
            f"<td>{_fmt(m.get('infer_seconds'), 2)}</td>"
            f"<td>{_fmt(m.get('shap_seconds'), 2)}</td>"
            f"<td>{_fmt_int(ep) if ep is not None else chr(8212)}</td></tr>"
        )
    return (
        f'<div class="tablewrap"><table><tbody>{kv}</tbody></table></div>'
        f"<h3>{_esc(L['timings'])}</h3>"
        '<div class="tablewrap"><table><thead><tr>'
        f"<th>{_esc(L['model'])}</th><th>{_esc(L['train_s'])}</th><th>{_esc(L['infer_s'])}</th>"
        f"<th>{_esc(L['shap_s'])}</th><th>{_esc(L['epochs'])}</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
    )


def render_report(results: dict, *, lang: str = "zh") -> str:
    L = LABELS.get(lang, LABELS["zh"])
    run = results.get("run") or {}
    all_models = []
    for i, (key, m) in enumerate((results.get("models") or {}).items()):
        mm = dict(m)
        mm["key"] = key
        mm["display"] = str(m.get("display") or key)
        mm["color"] = PALETTE[i % len(PALETTE)]
        all_models.append(mm)
    ok = [m for m in all_models if not m.get("failed") and m.get("metrics")]
    failed = [m for m in all_models if m.get("failed") or not m.get("metrics")]

    base = None
    for m in ok:
        n, npos = _num(m["metrics"].get("n")), _num(m["metrics"].get("n_pos"))
        if n and npos is not None:
            base = npos / n
            break
    if base is None:
        base = _num(run.get("bad_rate"))

    sections = []

    def sec(title, body):
        sections.append(f"<section><h2>{_esc(title)}</h2>{body}</section>")

    if failed:
        items = "".join(
            f"<li><b>{_esc(m['display'])}</b>: <code>{_esc(str(m.get('failed') or 'no metrics'))}"
            "</code></li>"
            for m in failed
        )
        sections.append(
            f'<div class="callout warn"><b>{_esc(L["failed"])}</b><ul>{items}</ul></div>'
        )
    if not ok:
        sections.append(f"<p>{_esc(L['no_models'])}</p>")
    else:
        sec(L["summary"], _legend(ok) + _summary_table(ok, L))
        roc = svg_lines(
            _curve_series(ok, "roc_curve", "fpr", "tpr"),
            xlabel="FPR",
            ylabel="TPR",
            diagonal=True,
        )
        pr = svg_lines(
            _curve_series(ok, "pr_curve", "recall", "precision"),
            xlabel="Recall",
            ylabel="Precision",
            baseline_y=base,
        )
        pr_note = (
            f'<p class="note">{_esc(L["baseline"])}: {_fmt(base, 4)}</p>'
            if base is not None
            else ""
        )
        sec(
            f"{L['roc']} / {L['pr']}",
            _legend(ok) + '<div class="grid">'
            f'<div class="card"><h3>{_esc(L["roc"])}</h3>{roc}</div>'
            f'<div class="card"><h3>{_esc(L["pr"])}</h3>{pr}{pr_note}</div></div>',
        )
        sec(
            f"{L['metrics']} / {L['operating']}",
            f"<h3>{_esc(L['metrics'])}</h3>{_heatmap(ok, L)}"
            f"<h3>{_esc(L['operating'])}</h3>{_confusion_table(ok, L)}",
        )
        sec(
            L["calibration"],
            _legend(ok) + f'<div class="card" style="max-width:640px">{_calibration_svg(ok, L)}'
            f'<p class="note">{_esc(L["ideal"])}: y = x</p></div>',
        )
        sec(L["shap"], _legend(ok) + _shap_section(ok, L))
    sec(L["details"], _details(run, all_models, L))

    return (
        '<!DOCTYPE html><html lang="' + ("zh" if lang == "zh" else "en") + '"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(L['title'])}</title><style>{_CSS}</style></head><body>"
        f"<main><header><h1>{_esc(L['title'])}</h1>"
        f'<div class="sub">{_esc(str(run.get("generated_at", "")))} · '
        f"<code>{_esc(str(run.get('data_dir', '')))}</code></div>"
        f"{_facts(run, L)}</header>{''.join(sections)}</main></body></html>"
    )

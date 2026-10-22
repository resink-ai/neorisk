"""`bench discover`'s single-file HTML report: inline SVG, light and dark, no network."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

from bench.discover.methods import BEFORE

COLORS = {"random": "#9aa0ad", "perfect": "#1f2433", "anomaly": "#6b7280",
          "connection": "#2f6fdf", "money_flow": "#0f9488", "reason_hop": "#1d4ed8",
          "similarity": "#d98a00", "reason_sim": "#a16207", "pu_learn_plain": "#e8a06a",
          "pu_learn": "#b8560f", "sync": "#7c4ddb", "rules": "#c2367a",
          "reason_rules": "#9d174d", "label_model": "#e0567a", "active_plain": "#ef8a98",
          "active": "#d23a4f", "vote_plain": "#86c27a", "vote": "#3d8b2f"}

TEXT = {
    "en": {"title": "Label discovery bench", "lead": "Every method starts from the same reported "
           "seeds and gets the same review budget. Scores are against the hidden ring labels.",
           "board": "Leaderboard at the full budget", "curves": "Bad users found per review",
           "sweep": "Label-set recall by review rounds", "rocpr": "Final ranking: ROC and PR "
           "(unreviewed users)", "seg": "Who gets missed, who gets flagged",
           "risk": "Ranking as a block list: approval rate vs bad share among approved",
           "method": "method", "found": "found", "recall_b": "recall @ budget",
           "prec": "label-set precision", "rec": "label-set recall", "auc": "AUC",
           "prauc": "PR-AUC", "stealth": "stealth recall", "visible": "visible recall",
           "fa_friend": "false alarm: promoted friends", "fa_prom": "false alarm: promoters",
           "fa_base": "false alarm: ordinary", "secs": "s / run",
           "reviews": "reviews spent", "badfound": "bad found", "rounds": "rounds of review",
           "approval": "approval rate", "badshare": "bad share among approved",
           "notes": "Label set = known bad plus the top-ranked unreviewed users, as many as there "
           "are bad users. Means over seed draws; ± is the spread.",
           "perfect": "perfect reads the hidden truth: it is the ceiling, not a contender.",
           "rp": "reason precision",
           "why": "Why are the seeds bad?",
           "why_lead": "The anomalies the reported seeds of the first draw carry, weighted by "
           "how far into the population's tail they sit. Anchored methods follow only these.",
           "seed": "seed", "reasons": "its strongest anomalies", "signal": "signal",
           "weight": "weight",
           "ba": "Before and after anchoring on the seeds' anomalies",
           "ba_lead": "Each anchored method next to the one it replaces, at the full budget. "
           "Reason precision is the share of a label set's unreviewed picks that carry the "
           "seeds' anomaly; it is computed from the world, not the truth.",
           "pair": "before → after",
           "rv": "Perfect reviewer → {name} reviewer",
           "rv_lead": "The same run with a reviewer who misses {miss:.0%} of visible and "
           "{stealth_miss:.0%} of stealth ring members, and calls {false_alarm:.0%} of ordinary "
           "and {promoter_false_alarm:.0%} of genuine promoters bad. Methods learn from those "
           "verdicts; scores stay against the hidden truth.",
           "wrong": "wrong verdicts"},
    "zh": {"title": "标签发现基准", "lead": "每个方法从相同的举报种子出发，审核预算相同；"
           "评分对照隐藏的团伙标签。",
           "board": "满预算排行榜", "curves": "每次审核找到的坏用户", "sweep": "不同审核轮数下的标签集召回",
           "rocpr": "最终排序：ROC 与 PR（未审核用户）", "seg": "漏掉了谁，误伤了谁",
           "risk": "把排序当拦截名单：通过率 vs 通过用户中的坏用户占比",
           "method": "方法", "found": "找到", "recall_b": "预算内召回", "prec": "标签集精确率",
           "rec": "标签集召回", "auc": "AUC", "prauc": "PR-AUC", "stealth": "隐身成员召回",
           "visible": "显性成员召回", "fa_friend": "误伤：被推广好友", "fa_prom": "误伤：推广者",
           "fa_base": "误伤：普通用户", "secs": "秒/次", "reviews": "已用审核数",
           "badfound": "找到的坏用户", "rounds": "审核轮数", "approval": "通过率",
           "badshare": "通过用户中坏用户占比",
           "notes": "标签集 = 已确认坏用户 + 排名最高的未审核用户，总数等于真实坏用户数。数值为多次种子抽样的均值，± 为波动。",
           "perfect": "perfect 直接读取真实标签，只作为上限，不参与比较。",
           "rp": "原因精确率",
           "why": "种子为什么是坏用户？",
           "why_lead": "第一次抽样的举报种子身上的异常，按其在总体尾部的位置加权。锚定方法只沿这些异常扩展。",
           "seed": "种子", "reasons": "最强的异常", "signal": "信号", "weight": "权重",
           "ba": "锚定种子异常前后对比",
           "ba_lead": "每个锚定方法与它替换的方法并列，取满预算。原因精确率 = 标签集中未审核用户里带有种子异常的比例，"
           "只用世界数据计算，不读真实标签。",
           "pair": "之前 → 之后",
           "rv": "完美审核员 → {name} 审核员",
           "rv_lead": "同一数据，换成会出错的审核员：漏判 {miss:.0%} 的可见团伙成员和 {stealth_miss:.0%} 的隐蔽成员，"
           "把 {false_alarm:.0%} 的普通用户和 {promoter_false_alarm:.0%} 的真实推广者判为坏。方法从这些判定中学习；"
           "评分仍对照隐藏真相。",
           "wrong": "错误判定"},
}

CSS = """
:root{--bg:#f5f6f9;--panel:#fff;--ink:#1a2033;--muted:#5d6580;--line:#dde1ea;--accent:#d98a00}
@media (prefers-color-scheme:dark){:root{--bg:#0f1322;--panel:#171c31;--ink:#e7eaf4;
--muted:#9aa2bd;--line:#2a3150;--accent:#f2a93b;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px 16px 48px}
main{max-width:1080px;margin:0 auto;display:grid;gap:18px}
h1{margin:0;font-size:26px}h2{margin:0 0 10px;font-size:17px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.muted{color:var(--muted)}.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{font-size:12px;color:var(--muted);font-weight:600}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
svg{width:100%;height:auto;display:block}svg text{fill:var(--muted);font-size:11px}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;margin-top:6px}
.legend i{display:inline-block;width:12px;height:3px;margin-right:5px;vertical-align:middle}
.sw{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
"""


def _f(x, d=3) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def _ms(a: dict, d=3) -> str:
    sd = a.get("sd")
    return _f(a["mean"], d) + (f" <span class='muted'>±{_f(sd, d)}</span>"
                               if sd is not None and not math.isnan(sd) and sd > 0 else "")


class Plot:
    """A line chart in data coordinates."""

    def __init__(self, x0, x1, y0, y1, w=480, h=300, xlabel="", ylabel="", pct=False,
                 xticks=None):
        self.x0, self.x1, self.y0, self.y1, self.w, self.h = x0, x1, y0, y1, w, h
        self.L, self.R, self.T, self.B = 52, w - 12, 12, h - 40
        self.parts: list[str] = []

        def pc(v, span):
            return f"{v:.1%}" if span < 0.1 else f"{v:.0%}"

        for i in range(5):
            yv = y0 + (y1 - y0) * i / 4
            y = self.Y(yv)
            lab = pc(yv, y1 - y0) if pct else (f"{yv:.2f}" if y1 <= 1.5 else f"{yv:.0f}")
            self.parts.append(f"<line x1='{self.L}' x2='{self.R}' y1='{y:.1f}' y2='{y:.1f}' "
                              f"stroke='var(--line)'/><text x='{self.L - 6}' y='{y + 4:.1f}' "
                              f"text-anchor='end'>{lab}</text>")
        for xv in (xticks if xticks is not None else
                   [x0 + (x1 - x0) * i / 4 for i in range(5)]):
            xl = pc(xv, x1 - x0) if pct else (f"{xv:.2f}" if x1 <= 1.5 else f"{xv:g}")
            self.parts.append(f"<text x='{self.X(xv):.1f}' y='{self.B + 16}' "
                              f"text-anchor='middle'>{xl}</text>")
        self.parts.append(f"<text x='{(self.L + self.R) / 2}' y='{h - 6}' "
                          f"text-anchor='middle'>{html.escape(xlabel)}</text>")
        self.parts.append(f"<text x='12' y='{(self.T + self.B) / 2}' text-anchor='middle' "
                          f"transform='rotate(-90 12 {(self.T + self.B) / 2})'>"
                          f"{html.escape(ylabel)}</text>")

    def X(self, v):
        return self.L + (self.R - self.L) * (v - self.x0) / ((self.x1 - self.x0) or 1)

    def Y(self, v):
        return self.B - (self.B - self.T) * (v - self.y0) / ((self.y1 - self.y0) or 1)

    def line(self, pts, color, dash=False, width=2.0):
        if not pts:
            return
        p = " ".join(f"{self.X(x):.1f},{self.Y(min(max(y, self.y0), self.y1)):.1f}"
                     for x, y in pts)
        self.parts.append(f"<polyline points='{p}' fill='none' stroke='{color}' "
                          f"stroke-width='{width}' stroke-linejoin='round'"
                          + (" stroke-dasharray='5 4'" if dash else "") + "/>")

    def svg(self) -> str:
        return f"<svg viewBox='0 0 {self.w} {self.h}'>{''.join(self.parts)}</svg>"


def _legend(keys) -> str:
    return "<div class='legend'>" + "".join(
        f"<span><i style='background:{COLORS.get(k, '#888')}'></i>{k}</span>" for k in keys
    ) + "</div>"


def render(res: dict, lang: str = "en") -> str:
    t = TEXT[lang]
    cfg, world, methods = res["config"], res["world"], res["methods"]
    keys = list(methods)
    full = str(cfg["rounds"])
    top = {k: methods[k]["by_budget"][full] for k in keys}
    to_find = world["bad"] - cfg["n_seeds"]
    rank = sorted(keys, key=lambda k: (k == "perfect", -top[k]["recall"]["mean"]))

    rows = []
    for k in rank:
        a = top[k]
        found = a["found"]["mean"][-1] if isinstance(a.get("found"), dict) and a["found"]["mean"] \
            else 0
        fa = a["false_alarm"]
        rows.append(
            f"<tr><td><span class='sw' style='background:{COLORS.get(k, '#888')}'></span>{k}</td>"
            f"<td>{found:.0f}</td><td>{_ms(a['recall_at_budget'])}</td>"
            f"<td>{_ms(a['precision'])}</td><td>{_ms(a['recall'])}</td>"
            f"<td>{_ms(a['auc'])}</td><td>{_ms(a['pr_auc'])}</td>"
            f"<td>{_ms(a['stealth_recall'])}</td><td>{_ms(a['visible_recall'])}</td>"
            f"<td>{_f(fa.get('promoted_friend', {}).get('mean'))}</td>"
            f"<td>{_f(fa.get('promoter', {}).get('mean'))}</td>"
            f"<td>{_f(fa.get('base', {}).get('mean'), 4)}</td>"
            f"<td>{_f(a.get('reason_precision', {}).get('mean'))}</td>"
            f"<td>{methods[k]['seconds']:.1f}</td></tr>")
    head = "".join(f"<th>{t[c]}</th>" for c in ("method", "found", "recall_b", "prec", "rec",
                                                  "auc", "prauc", "stealth", "visible",
                                                  "fa_friend", "fa_prom", "fa_base", "rp",
                                                  "secs"))

    def arrow(a: dict | None, b: dict | None, d: int = 3) -> str:
        return f"{_f(a and a.get('mean'), d)} → <b>{_f(b and b.get('mean'), d)}</b>"

    ba_rows = "".join(
        f"<tr><td>{old} → {new}</td>"
        f"<td>{arrow(top[old]['recall'], top[new]['recall'])}</td>"
        f"<td>{arrow(top[old]['auc'], top[new]['auc'])}</td>"
        f"<td>{arrow(top[old]['stealth_recall'], top[new]['stealth_recall'])}</td>"
        f"<td>{arrow(top[old]['false_alarm'].get('promoter'), top[new]['false_alarm'].get('promoter'))}</td>"
        f"<td>{arrow(top[old].get('reason_precision'), top[new].get('reason_precision'))}</td></tr>"
        for new, old in BEFORE.items() if new in top and old in top)
    ba_head = "".join(f"<th>{t[c]}</th>" for c in ("pair", "rec", "auc", "stealth", "fa_prom",
                                                     "rp"))
    why = (res.get("explain") or [None])[0]
    why_html = ""
    if why:
        wmax = max((w for _, w in why["top"]), default=1) or 1
        bars = "".join(
            f"<tr><td>{html.escape(n)}</td><td><svg viewBox='0 0 200 10' style='width:200px'>"
            f"<rect width='{200 * w / wmax:.1f}' height='10' fill='var(--accent)'/></svg></td>"
            f"<td>{w:.2f}</td></tr>" for n, w in why["top"])
        per_seed = "".join(f"<tr><td>{s}</td><td>{html.escape(', '.join(r) or '—')}</td></tr>"
                           for s, r in why["reasons"].items())
        why_html = (f"<section class='panel'><h2>{t['why']}</h2><p class='muted'>"
                    f"{t['why_lead']}</p><div class='two'><div class='scroll'><table><thead><tr>"
                    f"<th>{t['signal']}</th><th></th><th>{t['weight']}</th></tr></thead><tbody>"
                    f"{bars}</tbody></table></div><div class='scroll'><table><thead><tr>"
                    f"<th>{t['seed']}</th><th>{t['reasons']}</th></tr></thead><tbody>"
                    f"{per_seed}</tbody></table></div></div></section>")
    ba_html = (f"<section class='panel'><h2>{t['ba']}</h2><p class='muted'>{t['ba_lead']}</p>"
               f"<div class='scroll'><table><thead><tr>{ba_head}</tr></thead><tbody>{ba_rows}"
               f"</tbody></table></div></section>") if ba_rows else ""

    base = res.get("baseline") or {}
    rv = cfg.get("reviewer") or {"name": "perfect"}
    rv_rows = "".join(
        f"<tr><td><span class='sw' style='background:{COLORS.get(k, '#888')}'></span>{k}</td>"
        f"<td>{arrow(base[k]['recall'], top[k]['recall'])}</td>"
        f"<td>{arrow(base[k]['stealth_recall'], top[k]['stealth_recall'])}</td>"
        f"<td>{arrow(base[k]['auc'], top[k]['auc'])}</td>"
        f"<td>{arrow(base[k]['false_alarm'].get('promoter'), top[k]['false_alarm'].get('promoter'))}</td>"
        f"<td>{_f(top[k].get('wrong_labels', {}).get('mean'), 1)}</td></tr>"
        for k in rank if k in base)
    rv_head = "".join(f"<th>{t[c]}</th>" for c in ("method", "rec", "stealth", "auc",
                                                     "fa_prom", "wrong"))
    rv_html = (f"<section class='panel'><h2>{html.escape(t['rv'].format(**rv))}</h2>"
               f"<p class='muted'>{html.escape(t['rv_lead'].format(**rv))}</p>"
               f"<div class='scroll'><table><thead><tr>{rv_head}</tr></thead><tbody>{rv_rows}"
               f"</tbody></table></div></section>") if rv_rows else ""

    k_, R = cfg["k"], cfg["rounds"]
    cur = Plot(0, k_ * R, 0, min(world["bad"], k_ * R), xlabel=t["reviews"],
               ylabel=t["badfound"], xticks=[k_ * r for r in range(0, R + 1, max(R // 5, 1))])
    for k in rank:
        f = top[k]["found"]
        if isinstance(f, dict):
            cur.line([(0, 0)] + [((i + 1) * k_, v) for i, v in enumerate(f["mean"])],
                     COLORS.get(k, "#888"), dash=k in ("perfect", "random"))

    budgets = cfg["budgets"]
    sw = Plot(0, max(budgets), 0, 1, xlabel=t["rounds"], ylabel=t["rec"], xticks=budgets)
    for k in rank:
        sw.line([(b, methods[k]["by_budget"][str(b)]["recall"]["mean"]) for b in budgets],
                COLORS.get(k, "#888"), dash=k in ("perfect", "random"))

    roc = Plot(0, 1, 0, 1, xlabel="FPR", ylabel="TPR")
    pr = Plot(0, 1, 0, 1, xlabel="recall", ylabel="precision")
    roc.line([(0, 0), (1, 1)], "var(--line)", dash=True, width=1)
    for k in rank:
        if k == "perfect":
            continue
        roc.line(top[k].get("roc") or [], COLORS.get(k, "#888"))
        pr.line(top[k].get("pr") or [], COLORS.get(k, "#888"))

    seg_rows = "".join(
        f"<tr><td>{k}</td><td><svg viewBox='0 0 200 14' style='width:200px'>"
        f"<rect width='{200 * (top[k]['visible_recall']['mean'] or 0):.1f}' height='6' "
        f"fill='{COLORS.get(k, '#888')}'/><rect y='8' width="
        f"'{200 * (top[k]['stealth_recall']['mean'] or 0):.1f}' height='6' "
        f"fill='{COLORS.get(k, '#888')}' opacity='.45'/></svg></td>"
        f"<td>{_f(top[k]['visible_recall']['mean'])}</td>"
        f"<td>{_f(top[k]['stealth_recall']['mean'])}</td></tr>"
        for k in rank if k != "perfect")

    risk_pts = {k: top[k]["risk"]["mean"] for k in rank
                if isinstance(top[k].get("risk"), dict)}
    ymax = max((p[1] for v in risk_pts.values() for p in v), default=0.02) * 1.1 or 0.02
    xmin = min((p[0] for v in risk_pts.values() for p in v), default=0.9)
    rk = Plot(math.floor(xmin * 100) / 100, 1, 0, ymax, xlabel=t["approval"],
              ylabel=t["badshare"], pct=True)
    for k, pts in risk_pts.items():
        rk.line(sorted(pts), COLORS.get(k, "#888"), dash=k in ("perfect", "random"))

    chips = "".join(f"<span class='chip'>{html.escape(s)}</span>" for s in (
        f"{world['users']:,} users", f"{world['bad']} bad ({world['stealth']} stealth)",
        f"{cfg['n_seeds']} seeds by day {cfg['report_day']:g}",
        f"{cfg['k']} reviews × {cfg['rounds']} rounds",
        f"reviewer: {(cfg.get('reviewer') or {}).get('name', 'perfect')}",
        f"{cfg['draws']} seed draws",
        f"{to_find} to find"))
    return f"""<!doctype html><html lang="{'zh-CN' if lang == 'zh' else 'en'}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t['title']}</title><style>{CSS}</style></head><body><main>
<header><h1>{t['title']}</h1><p class="muted">{t['lead']}</p><div class="chips">{chips}</div>
</header>
<section class="panel"><h2>{t['board']}</h2><div class="scroll"><table><thead><tr>{head}</tr>
</thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="muted">{t['notes']} {t['perfect']}</p></section>
{rv_html}{why_html}{ba_html}
<section class="two"><div class="panel"><h2>{t['curves']}</h2>{cur.svg()}{_legend(rank)}</div>
<div class="panel"><h2>{t['sweep']}</h2>{sw.svg()}{_legend(rank)}</div></section>
<section class="panel"><h2>{t['rocpr']}</h2><div class="two"><div>{roc.svg()}</div>
<div>{pr.svg()}</div></div>{_legend([k for k in rank if k != 'perfect'])}</section>
<section class="two"><div class="panel"><h2>{t['seg']}</h2><div class="scroll"><table><thead>
<tr><th>{t['method']}</th><th></th><th>{t['visible']}</th><th>{t['stealth']}</th></tr></thead>
<tbody>{seg_rows}</tbody></table></div></div>
<div class="panel"><h2>{t['risk']}</h2>{rk.svg()}{_legend(list(risk_pts))}</div></section>
</main></body></html>"""


def write(res: dict, out: str | Path, lang: str = "en") -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "discover.json").write_text(json.dumps(res, indent=1))
    p = out / "discover.html"
    p.write_text(render(res, lang), encoding="utf-8")
    return p

"""Report section describing how the benchmark data was generated (datagen fraud scenario)."""

import html as _html

_esc = _html.escape

# Mirrors datagen.scenarios.fraud (attributes, planted behaviours, scorer weights); the config
# values and observed counts come from the run's dataset_meta, so they always match the data.
_USER = [
    ("age_bucket", "low (10)", "static"),
    ("currency", "low (5)", "static"),
    ("state", "low (50)", "slow"),
    ("street", "high", "slow"),
    ("zip", "high", "slow"),
    ("segment", "low (8)", "slow"),
]
_DEVICE = [
    ("os", "low (4)", "static"),
    ("model", "low (30)", "static"),
    ("battery", "low (10)", "fast"),
    ("ip", "high", "slow"),
    ("user_agent", "low (20)", "slow"),
]
_PRODUCT = [("category", "low (20)", "static"), ("launch_day", "high (3650)", "static")]
_WEIGHTS = [
    ("amt_ratio_30d", 1.0),
    ("u_amt_count_7d", 0.3),
    ("u_amt_max_30d", 0.4),
    ("dev_users_n_unique_7d", 0.8),
    ("addr_chg_sum_30d", 0.5),
    ("inv_bonus_count_30d", 0.8),
    ("inv_bonus_sum_30d", 1.0),
    ("inv_zombie_mean_30d", 1.2),
    ("invr_bonus_count_30d", 0.8),
    ("invr_bonus_sum_30d", 1.0),
    ("invr_zombie_mean_30d", 1.2),
]

T = {
    "zh": {
        "intro": (
            "数据由 datagen 的 fraud 场景合成：先采样实体与事件，再按时间点计算隐藏的"
            "“黄金特征”，用固定权重的 XGBoost 打分、校准到目标坏账率后抽样出标签。"
            "基准测试只能看到原始事件列，看不到黄金特征和分数，因此真实信号是已知的。"
        ),
        "steps_h": "生成流程",
        "steps": [
            "实体：生成 user / device / product 的 UUID 与属性，属性按变更点时间线随时间变化。",
            "事件：生成交易与邀请事件（均为合成整数值），按事件时间关联各实体当时的属性。",
            "植入行为：多账号共用设备、预热后套现、赏金猎人与僵尸受邀人（见下表）。",
            "黄金特征：对每个事件只用其之前的数据（窗口 [t-w, t)）滚动计算 7/14/30 天特征与图特征。",
            "打分与标签：预设权重的 XGBoost 给出概率，校准到目标坏账率，再按伯努利抽样得到 label。",
            "导出：events.parquet 仅含原始列与 label；golden.parquet 单独存放，并有泄漏检查。",
        ],
        "attrs_h": "实体属性（取值均为合成整数）",
        "cols": ["实体", "属性", "基数", "变化速度"],
        "vol": {"static": "静态", "slow": "慢变", "fast": "快变（随机游走）"},
        "behav_h": "植入的风险行为",
        "behav": [
            (
                "活跃度偏斜",
                "用户交易量服从偏斜分布，少数用户非常活跃；10% 的交易发生在随机设备上。",
            ),
            (
                "预热后套现",
                "3% 的用户先发小额交易（金额 ×0.3），最后 10% 的交易放大 ×15。",
            ),
            (
                "赏金猎人",
                "少量早期用户作为猎人，邀请的人更多；来自猎人的邀请奖金 30–99，普通邀请 1–9。",
            ),
            (
                "僵尸受邀人",
                (
                    "猎人邀请的人有 90% 是僵尸（普通邀请 2%）；僵尸几乎不活跃，只在被邀请后约 2 天内"
                    "发出约 3 笔小额交易。"
                ),
            ),
            ("多账号同设备", "70% 的猎人僵尸受邀人与邀请人共用同一台设备。"),
        ],
        "golden_h": "黄金特征与打分权重",
        "golden_note": (
            "下列特征组合后经预设 XGBoost（拟合到权重加权的 tanh 教师函数）得到分数；"
            "inv_* 为被邀请一侧，invr_* 为邀请人一侧。窗口均严格取事件之前的数据。"
        ),
        "golden_cols": ["特征", "权重"],
        "cfg_h": "本次运行的生成参数与实际规模",
        "cfg_cols": ["参数", "值"],
        "cfg": {
            "n_events": "事件数",
            "seed": "随机种子",
            "span_days": "时间跨度（天）",
            "target_bad_rate": "目标坏账率",
            "invite_frac": "被邀请用户占比",
            "hunter_prob": "邀请来自猎人的概率",
            "users_per_event": "每事件对应用户数",
        },
        "obs": {
            "n_users": "出现的用户数",
            "n_devices": "出现的设备数",
            "n_products": "出现的商品数",
            "n_txn": "交易事件数",
            "n_invite": "邀请事件数",
            "n_bad": "坏样本数",
        },
        "limits_h": "使用时请注意",
        "limits": [
            "这是合成数据：模型分数反映的是被植入的信号，不代表真实业务中的表现。",
            "标签由概率抽样得到，因此存在不可约噪声，AUC 不会接近 1。",
            "基准特征只用原始事件计算，golden.parquet 中的特征与分数不参与训练。",
        ],
    },
    "en": {
        "intro": (
            "The data comes from the datagen fraud scenario: entities and events are sampled, "
            "hidden golden features are computed point-in-time, a fixed-weight XGBoost scorer "
            "turns them into probabilities, and labels are drawn after calibrating to the target "
            "bad rate. The benchmark sees only raw event columns, never the golden features or "
            "the score, so the true signal is known."
        ),
        "steps_h": "Generation pipeline",
        "steps": [
            (
                "Entities: UUIDs and attributes for users, devices and products; attributes change "
                "over time along change-point timelines."
            ),
            (
                "Events: transaction and invite events with synthetic integer values, joined to each "
                "entity's attributes as of the event time."
            ),
            (
                "Planted behaviour: shared devices, warm-up then cash-out, bounty hunters and zombie "
                "invitees (table below)."
            ),
            (
                "Golden features: rolling 7/14/30-day and graph features using only data strictly "
                "before each event (window [t-w, t))."
            ),
            (
                "Scoring and labels: preset-weight XGBoost gives a probability, calibrated to the "
                "target bad rate, then Bernoulli-sampled into label."
            ),
            (
                "Export: events.parquet holds raw columns and label only; golden.parquet is kept "
                "separate behind a leakage guard."
            ),
        ],
        "attrs_h": "Entity attributes (values are synthetic integers)",
        "cols": ["Entity", "Attribute", "Cardinality", "Volatility"],
        "vol": {"static": "static", "slow": "slow", "fast": "fast (random walk)"},
        "behav_h": "Planted risk behaviour",
        "behav": [
            (
                "Skewed activity",
                (
                    "Per-user volume is skewed so a few users are very active; 10% of transactions "
                    "use a random device."
                ),
            ),
            (
                "Warm-up then cash-out",
                (
                    "3% of users send small amounts first (x0.3), then their last 10% of "
                    "transactions are scaled x15."
                ),
            ),
            (
                "Bounty hunters",
                (
                    "A few early users act as hunters and invite more; hunter invites carry a bonus "
                    "of 30-99, ordinary invites 1-9."
                ),
            ),
            (
                "Zombie invitees",
                (
                    "90% of hunter invitees are zombies (2% for ordinary invites); zombies are "
                    "nearly inactive apart from about 3 small transactions in the 2 days after the "
                    "invite."
                ),
            ),
            (
                "Shared devices",
                "70% of hunter zombie invitees reuse the inviter's device.",
            ),
        ],
        "golden_h": "Golden features and scorer weights",
        "golden_note": (
            "These features feed a preset XGBoost fitted to a weighted tanh teacher to produce "
            "the score. inv_* is the invitee side, invr_* the inviter side. Windows use only "
            "data strictly before the event."
        ),
        "golden_cols": ["Feature", "Weight"],
        "cfg_h": "Generation parameters and realised size for this run",
        "cfg_cols": ["Parameter", "Value"],
        "cfg": {
            "n_events": "Events",
            "seed": "Seed",
            "span_days": "Span (days)",
            "target_bad_rate": "Target bad rate",
            "invite_frac": "Share of users invited",
            "hunter_prob": "Chance an invite is from a hunter",
            "users_per_event": "Users per event",
        },
        "obs": {
            "n_users": "Users seen",
            "n_devices": "Devices seen",
            "n_products": "Products seen",
            "n_txn": "Transaction events",
            "n_invite": "Invite events",
            "n_bad": "Bad labels",
        },
        "limits_h": "Read with care",
        "limits": [
            "The data is synthetic: scores reflect the planted signal, not real-world performance.",
            (
                "Labels are sampled from probabilities, so there is irreducible noise and AUC stays "
                "well below 1."
            ),
            (
                "Benchmark features use raw events only; golden features and the score are never "
                "used for training."
            ),
        ],
    },
}


def _table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_esc(h)}</th>" for h in head)
    body = "".join(
        "<tr>" + "".join(f'<td style="text-align:left">{_esc(str(c))}</td>' for c in r) + "</tr>"
        for r in rows
    )
    return (
        f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


def _fmt_val(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def render_datagen(run: dict, lang: str) -> str:
    t = T.get(lang, T["zh"])
    meta = run.get("dataset_meta") or {}
    cfg = meta.get("config") or {}
    obs = meta.get("observed") or {}
    attrs = (
        [["user", *r] for r in _USER]
        + [["device", *r] for r in _DEVICE]
        + [["product", *r] for r in _PRODUCT]
    )
    attrs = [[e, a, c, t["vol"][v]] for e, a, c, v in attrs]
    cfg_rows = [[t["cfg"][k], _fmt_val(cfg[k])] for k in t["cfg"] if k in cfg]
    cfg_rows += [[t["obs"][k], _fmt_val(obs[k])] for k in t["obs"] if k in obs]
    cfg_html = _table(t["cfg_cols"], cfg_rows) if cfg_rows else ""
    behav = _table([t["behav_h"], ""], [[a, b] for a, b in t["behav"]]).replace("<th></th>", "")
    return (
        f'<p class="note">{_esc(t["intro"])}</p>'
        f"<h3>{_esc(t['steps_h'])}</h3><ol>"
        + "".join(f"<li>{_esc(s)}</li>" for s in t["steps"])
        + "</ol>"
        f"<h3>{_esc(t['attrs_h'])}</h3>{_table(t['cols'], attrs)}"
        f"<h3>{_esc(t['behav_h'])}</h3>{behav}"
        f'<h3>{_esc(t["golden_h"])}</h3><p class="note">{_esc(t["golden_note"])}</p>'
        f"{_table(t['golden_cols'], [[f, f'{w:g}'] for f, w in _WEIGHTS])}"
        f"<h3>{_esc(t['cfg_h'])}</h3>{cfg_html}"
        f'<div class="callout warn"><b>{_esc(t["limits_h"])}</b>{_ul(t["limits"])}</div>'
    )

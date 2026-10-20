"""Report section describing how the benchmark data was generated: the e-commerce
pack plus the `bounty_hunters` overlay, exported by `datagen export --legacy-fraud` (D87)."""

import html as _html

_esc = _html.escape

# Mirrors the e-commerce pack, the bounty_hunters overlay and the legacy adapter
# (`neorisk_simkit.io.legacy`); the run's identity, overlay parameters and counts come from
# the run's dataset_meta (`meta["source"]` and `meta`), so they always match the data.
_USER = [
    ("age_bucket", "low (5)", "static"),
    ("segment", "low (5)", "static"),
    ("state", "low (50)", "slow"),
]
_DEVICE = [("os", "low (5)", "static"), ("model", "low (3)", "static")]
_PRODUCT = [("category", "low (24)", "static"), ("price", "high", "static")]
_GOLDEN = [
    ("u_amt_{count,sum,mean,max,min}_{7,14,30}d", "user"),
    ("amt_ratio_30d", "user"),
    ("dev_users_n_unique_7d", "device"),
    ("inv_bonus_{count,sum,mean,max}_{7,14,30}d", "invitee"),
    ("invr_bonus_{count,sum,mean,max}_{7,14,30}d", "inviter"),
    ("invitee_is_zombie", "truth"),
    ("actor_role", "truth"),
    ("score", "truth"),
]

T = {
    "zh": {
        "intro": (
            "数据由 datagen 的智能体事件模拟器生成：examples/ecommerce 电商数据包模拟正常购物者，"
            "bounty_hunters 叠加层注入刷推荐奖励的团伙，再由 datagen export --legacy-fraud "
            "导出为基准测试使用的格式。标签来自叠加层的隐藏真值（labels/），"
            "基准测试只能看到原始事件列，看不到黄金特征和真值，因此真实信号是已知的。"
        ),
        "steps_h": "生成流程",
        "steps": [
            ("电商包：购物者注册、在会话中浏览商品、加入购物车、结账；结账向库存分片预留库存，"
             "付款授权后下单，订单再经履约（发货、送达、退货）。"),
            ("推荐计划：受邀用户首笔订单达到最低金额后，向推荐奖金池分片申领奖励，"
             "邀请人与受邀人各得奖金；奖金池按周期设有预算上限。"),
            ("叠加层：bounty_hunters 按到达时间加入团伙，每个团伙由一个活动执行者运行"
             "猎人与其僵尸账号，只通过电商包公开的动作产生同样的事件。"),
            ("隐藏标签：叠加层把每个成员的角色（猎人、僵尸）与结果写入 labels/，"
             "正常购物者没有标签。"),
            ("导出：order_placed 记为交易（event_type 0），邀请人的 referral_bonus_paid "
             "记为邀请（event_type 1）；属性按事件时间取值；label = 行的用户"
             "（邀请行为其邀请人）是带标签的团伙成员。"),
            ("黄金特征：对每个事件只用其之前的数据（窗口 [t-w, t)）滚动计算 7/14/30 天特征与"
             "图特征；events.parquet 仅含原始列与 label，golden.parquet 单独存放。"),
        ],
        "attrs_h": "实体属性（取值均为整数编码）",
        "cols": ["实体", "属性", "基数", "变化速度"],
        "vol": {"static": "静态", "slow": "慢变（地址变更）"},
        "behav_h": "电商包与叠加层的行为",
        "behav": [
            (
                "会话与购物车",
                "购物者在会话中浏览商品并加入购物车，部分会话进入结账；活跃度呈长尾分布。",
            ),
            (
                "库存与订单",
                "结账时逐行预留库存，缺货则整单失败；付款授权失败会释放库存。",
            ),
            (
                "推荐",
                "部分购物者邀请朋友；受邀人首单达到最低金额后申领推荐奖金。",
            ),
            (
                "团伙",
                "每个团伙由一名猎人和若干僵尸账号组成，猎人等待僵尸领到奖金后下单套现。",
            ),
            (
                "最低金额的僵尸订单",
                "多数僵尸注册后很快下一笔略高于推荐最低金额的订单，以满足领奖条件，然后不再活跃。",
            ),
            ("共用设备", "僵尸账号按比例复用猎人的设备。"),
            (
                "奖金池耗尽",
                ("僵尸与正常用户从同一个有预算上限的奖金池申领，团伙会耗尽预算，"
                 "使正常用户的申领被拒绝。"),
            ),
        ],
        "golden_h": "黄金特征与隐藏真值",
        "golden_note": (
            "golden.parquet 中的特征只用事件之前的数据计算；inv_* 为被邀请一侧，"
            "invr_* 为邀请人一侧。invitee_is_zombie、actor_role 与 score（= label）"
            "来自叠加层的真值，仅供 --oracle 上限参考。"
        ),
        "golden_cols": ["特征", "类别"],
        "kind": {"user": "用户", "device": "设备", "invitee": "被邀请一侧",
                 "inviter": "邀请人一侧", "truth": "真值"},
        "cfg_h": "本次运行的来源、参数与实际规模",
        "cfg_cols": ["参数", "值"],
        "src": {"pack": "电商包", "revision": "包版本", "run": "运行"},
        "cfg": {
            "seed": "随机种子",
            "n_events": "事件数",
            "bad_rate": "坏样本率",
        },
        "overlay": "叠加层参数",
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
            "这是合成数据：模型分数反映的是模拟出的行为，不代表真实业务中的表现。",
            "标签是团伙成员身份，未考虑标签成熟时间；团伙规模由叠加层参数决定。",
            "导出不含预热期的历史：预热期内的地址变更不可见，用户所在地回落到注册时的取值。",
            "基准特征只用原始事件计算，golden.parquet 中的特征与真值不参与训练。",
        ],
    },
    "en": {
        "intro": (
            "The data comes from datagen's agentic event simulator: the e-commerce pack (examples/ecommerce) "
            "simulates ordinary shoppers, the bounty_hunters overlay adds rings that farm the "
            "referral program, and datagen export --legacy-fraud writes the run in the "
            "benchmark's format. Labels come from the overlay's hidden ground truth (labels/). "
            "The benchmark sees only raw event columns, never the golden features or the "
            "ground truth, so the true signal is known."
        ),
        "steps_h": "Generation pipeline",
        "steps": [
            (
                "E-commerce pack: shoppers sign up, browse products in sessions, add them to a "
                "cart and check out; checkout reserves stock on the inventory shard, an order "
                "is placed once payment is authorized, and fulfillment ships, delivers and "
                "takes returns."
            ),
            (
                "Referral program: when an invitee's first order reaches the minimum, a claim "
                "goes to the referral pool shard and both inviter and invitee are paid; the "
                "pool has a budget per period."
            ),
            (
                "Overlay: bounty_hunters rings arrive over time; one campaign owner runs each "
                "hunter and its zombies, which emit the same events through the actions the "
                "pack exposes."
            ),
            (
                "Hidden labels: the overlay writes each member's role (hunter, zombie) and "
                "outcome to labels/; ordinary shoppers have no label."
            ),
            (
                "Export: order_placed becomes a transaction (event_type 0) and the inviter's "
                "referral_bonus_paid an invite (event_type 1); attributes are taken as of the "
                "event time; label = the row's user (the inviter on invite rows) is a labeled "
                "ring member."
            ),
            (
                "Golden features: rolling 7/14/30-day and graph features using only data "
                "strictly before each event (window [t-w, t)); events.parquet holds raw "
                "columns and label only, golden.parquet is kept separate."
            ),
        ],
        "attrs_h": "Entity attributes (values are integer codes)",
        "cols": ["Entity", "Attribute", "Cardinality", "Volatility"],
        "vol": {"static": "static", "slow": "slow (address changes)"},
        "behav_h": "Pack and overlay behaviour",
        "behav": [
            (
                "Sessions and carts",
                (
                    "Shoppers browse products in sessions and add them to a cart; some sessions "
                    "check out. Activity is heavy-tailed."
                ),
            ),
            (
                "Inventory and orders",
                (
                    "Checkout reserves stock line by line and fails as a whole when a line is "
                    "out of stock; a failed payment authorization releases the stock."
                ),
            ),
            (
                "Referrals",
                (
                    "Some shoppers invite friends; an invitee's first order at or above the "
                    "minimum claims the referral bonus."
                ),
            ),
            (
                "Rings",
                (
                    "Each ring is one hunter and its zombie accounts; the hunter waits until "
                    "its zombies are paid, then cashes out with orders of its own."
                ),
            ),
            (
                "Zombies at the minimum order",
                (
                    "Zombies sign up through the hunter's invite; most soon place one order just "
                    "above the referral minimum to qualify, then go dormant."
                ),
            ),
            ("Shared devices", "A share of zombies reuse the hunter's devices."),
            (
                "Pool draining",
                (
                    "Zombies and ordinary shoppers claim from the same capped pool, so rings "
                    "drain the budget and ordinary claims get rejected."
                ),
            ),
        ],
        "golden_h": "Golden features and hidden ground truth",
        "golden_note": (
            "Golden features use only data strictly before each event. inv_* is the invitee "
            "side, invr_* the inviter side. invitee_is_zombie, actor_role and score (= label) "
            "come from the overlay's ground truth and only feed the --oracle ceiling."
        ),
        "golden_cols": ["Feature", "Kind"],
        "kind": {"user": "user", "device": "device", "invitee": "invitee side",
                 "inviter": "inviter side", "truth": "ground truth"},
        "cfg_h": "Source, parameters and realised size for this run",
        "cfg_cols": ["Parameter", "Value"],
        "src": {"pack": "Pack", "revision": "Pack revision", "run": "Run"},
        "cfg": {
            "seed": "Seed",
            "n_events": "Events",
            "bad_rate": "Bad rate",
        },
        "overlay": "overlay parameter",
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
            ("The data is synthetic: scores reflect the simulated behaviour, not real-world "
             "performance."),
            (
                "Labels are ring membership with label maturity ignored; ring size is set by "
                "the overlay's parameters."
            ),
            (
                "The export has no warm-up history: an address change during warm-up is not "
                "seen, so the user's state falls back to its value at creation."
            ),
            (
                "Benchmark features use raw events only; golden features and the ground truth "
                "are never used for training."
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


def _cfg_rows(t: dict, meta: dict) -> list[list[str]]:
    src = meta.get("source") or {}
    obs = meta.get("observed") or {}
    rows = [[t["src"][k], _fmt_val(src[k])] for k in t["src"] if src.get(k) is not None]
    rows += [[t["cfg"][k], _fmt_val(meta[k])] for k in t["cfg"] if meta.get(k) is not None]
    for name, params in (src.get("overlays") or {}).items():
        rows += [[f"{name}.{p} ({t['overlay']})", _fmt_val(v)]
                 for p, v in (params or {}).items()]
    rows += [[t["obs"][k], _fmt_val(obs[k])] for k in t["obs"] if k in obs]
    return rows


def render_datagen(run: dict, lang: str) -> str:
    t = T.get(lang, T["zh"])
    meta = run.get("dataset_meta") or {}
    attrs = (
        [["user", *r] for r in _USER]
        + [["device", *r] for r in _DEVICE]
        + [["product", *r] for r in _PRODUCT]
    )
    attrs = [[e, a, c, t["vol"][v]] for e, a, c, v in attrs]
    cfg_rows = _cfg_rows(t, meta)
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
        f"{_table(t['golden_cols'], [[f, t['kind'][k]] for f, k in _GOLDEN])}"
        f"<h3>{_esc(t['cfg_h'])}</h3>{cfg_html}"
        f'<div class="callout warn"><b>{_esc(t["limits_h"])}</b>{_ul(t["limits"])}</div>'
    )

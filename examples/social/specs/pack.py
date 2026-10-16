"""Microblogging social network pack.

Partitions
    owner  user        one account: profile, status, sessions, follow changes since the epoch
    owner  cascade     one original post and its whole repost tree (keyed by the root post_id)
    shard  moderation  one review queue: queued reports, decided items, author strikes

Read inputs (immutable within an epoch; rebuilt at aligned step boundaries from sealed events)
    follow_graph    CSR, rebuilt weekly from the previous graph + follow/unfollow events
    account_status  suspended-account bitset, rebuilt hourly from account_suspended events
    profile, topic  static attributes (latent activity, influence, interests; topic virality)

Boundaries (immutable request/response or message, latency >= delta)
    cascade    -> moderation  report a post or reply                       delta 1 s
    moderation -> cascade     label / takedown decision      message, next step or later
    moderation -> user        suspend the author             message, next step or later
    user       -> cascade     author suspended, close cascade  message, next step or later
    user       -> cascade     create the cascade for a new post (creation message)
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import boolean, cat, f64, hidden, i16, i32, i64, opt, ref, ts

from . import kernels as k

PACK = "social"
SCHEMA_VERSION = 1

TOPICS = (
    "news", "politics", "world", "business", "finance", "crypto", "tech", "science", "health",
    "fitness", "food", "travel", "fashion", "beauty", "music", "film", "tv", "books", "art",
    "photography", "gaming", "esports", "sports", "football", "basketball", "cricket", "memes",
    "humor", "pets", "parenting", "education", "careers", "cars", "diy", "outdoors", "weather",
    "religion", "local", "personal", "other",
)
REGIONS = ("na", "latam", "eu", "mena", "africa", "south_asia", "east_asia", "oceania")
CLIENTS = ("ios", "android", "web")
ACQUISITION = ("organic", "search_ad", "social_ad", "referral", "press")
FOLLOW_SOURCES = ("onboarding", "follow_back", "friend_of_friend", "popular", "topic")
POLICIES = ("none", "spam", "abuse", "misinfo")              # hidden truth and decided policy
DECISIONS = ("no_action", "label", "takedown", "suspend_author")
CLOSE_REASONS = ("quiet", "max_age", "takedown", "author_suspended")


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Activity:
    """Account behavior; consumed by kernels.user_activity."""
    session_gap_alpha: float = 1.3          # Pareto tail of gaps, scaled by profile.activity
    session_gap_min_h: float = 0.5
    session_len: dist.Dist = dist.lognormal(median_s=240, sigma=0.9)
    posts_per_session: float = 0.12         # Poisson mean, times profile.poster
    follow_p: float = 0.06                  # per session
    unfollow_p: float = 0.01                # per session
    onboarding_follows: dist.Dist = dist.geometric(mean=8.0, min=3, max=20)
    follow_source_mix: tuple = (0.0, 0.30, 0.35, 0.20, 0.15)   # FOLLOW_SOURCES, onboarding=0
    max_following: int = 5_000
    max_edge_changes: int = 256             # follows/unfollows per user per graph epoch
    live_posts: int = 16                    # recent cascades remembered (kernels.LIVE_POSTS)
    violation_p: tuple = (0.994, 0.003, 0.002, 0.001)          # POLICIES for organic posts
    media_p: float = 0.35


@dataclass(frozen=True)
class Graph:
    epoch: str = "7d"                       # follow_graph rebuild period
    status_epoch: str = "1h"                # account_status rebuild period
    out_degree: dist.Dist = dist.pareto(alpha=1.4, min=5, max=5_000)   # following; pdf tail 2.4
    in_weight: str = "profile.influence"    # degree-corrected: followers ~ influence
    reciprocity: float = 0.22
    topic_homophily: float = 0.4            # share of edges chosen within a shared topic


@dataclass(frozen=True)
class Cascade:
    """Spread of one post down the follower graph; consumed by kernels.cascade."""
    fanout_substep: int = 64                # followers per sub-step (fixed, not buffer-sized)
    see_window_h: float = 36.0              # a follower sees it if they open the app in time
    influence_boost: float = 0.5            # feed rank boost per unit of author influence
    topic_boost: float = 1.6                # follower interested in the post's topic
    exposure_delay: dist.Dist = dist.shifted_lognormal(min_s=1, median_s=2_700, sigma=1.5)
    impression_sample_every: int = 20       # log 1 in 20 impressions, weight 20
    like_p: float = 0.022
    reply_p: float = 0.0025
    repost_p: float = 0.0045                # times post virality, decayed by depth
    depth_decay: float = 0.7
    label_damping: float = 0.3              # repost and like multiplier after a warning label
    report_p: tuple = (0.00002, 0.004, 0.006, 0.003)   # per exposure, by hidden policy
    reply_abuse_p: float = 0.002            # organic replies that are abusive (hidden)
    virality: dist.Dist = dist.lognormal(median=1.0, sigma=0.8, max=12.0)  # times topic virality
    quiet_after: str = "12h"                # close once nothing is pending for this long
    max_age: str = "7d"
    max_reposts: int = 20_000               # declared caps; checked as laws
    max_depth: int = 40
    max_exposed: int = 250_000              # dedup set hard cap
    max_replies: int = 50_000
    max_live: int = 400_000                 # live cascades at once


@dataclass(frozen=True)
class Moderation:
    queues: int = 4                         # moderation shards, routed by reported author
    review_tick: str = "5m"
    reviews_per_hour: float = 900.0         # per queue at the daily peak
    night_capacity: float = 0.35            # share of peak capacity at 03:00 local
    max_queue: int = 200_000                # beyond this, reports are dropped (and counted)
    strike_limit: int = 3                   # upheld violations before suspension
    action_p: tuple = (0.04, 0.80, 0.70, 0.65)        # P(any action | hidden policy)
    label_share: tuple = (0.7, 0.05, 0.15, 0.85)      # of actions, share that are labels
    decided_ttl: str = "30d"


@dataclass(frozen=True)
class Config:
    users: int = 200_000                    # population at the end of the span
    initial_share: float = 0.85             # share that exists at the start
    activity: Activity = field(default_factory=Activity)
    graph: Graph = field(default_factory=Graph)
    cascade: Cascade = field(default_factory=Cascade)
    moderation: Moderation = field(default_factory=Moderation)
    execution_owner: str = "user_id"        # overlays may group cohort members under another owner
    cascade_execution_owner: str = "post_id"   # ... and carry their members' cascades along


# --------------------------------------------------------------------------- pack
def define(p: Pack, cfg: Config) -> None:
    a, g, c, m = cfg.activity, cfg.graph, cfg.cascade, cfg.moderation

    # ---------------------------------------------------------------- read inputs
    topic = p.table("topic", key="topic_id", mutable=False, doc="Topics, fixed for the run", cols={
        "name": cat(*TOPICS),
        "virality": f64(min=0),             # multiplies post virality
        "report_propensity": f64(min=0),    # multiplies report_p
    }, source=std.catalog(
        n=len(TOPICS), name=TOPICS,
        virality=std.by_name({"news": 2.0, "memes": 2.5, "humor": 2.0, "politics": 1.8,
                              "crypto": 1.5, "personal": 0.3, "otherwise": 1.0}),
        report_propensity=std.by_name({"politics": 3.0, "health": 2.0, "crypto": 2.0,
                                       "religion": 2.0, "otherwise": 1.0}),
    ))

    # Static attributes drawn by the population source; readable by any partition from the
    # user's creation time. Exogenous, never written, so not mutable state.
    profile = p.table("profile", key="user_id", mutable=False, doc="Latent account attributes",
                      cols={
        "activity": f64(min=0),             # expected sessions per day
        "influence": f64(min=0),            # feed rank weight and follower attractiveness
        "poster": f64(min=0),               # posting propensity
        "interests": "i16[3]",              # topic ids
    }, source=std.from_population("user", cols={
        "activity": dist.lognormal(median=0.6, sigma=1.1, max=40.0),
        "influence": dist.pareto(alpha=1.2, min=0.1, max=1_000.0),   # in-degree pdf tail ~2.2
        "poster": dist.lognormal(median=0.25, sigma=1.6, max=60.0),
        "interests": dist.categorical_zipf(TOPICS, s=0.9, k=3, distinct=True),
    }))

    # ---------------------------------------------------------------- owner state
    user = p.table("user", key="user_id", mutable=True, doc="An account", cols={
        "signup_at": ts(),
        "region": cat(*REGIONS),
        "client": cat(*CLIENTS),
        "acquisition": cat(*ACQUISITION),
        "status": cat("active", "suspended"),
        "posts": i32(min=0),
        "suspended_at": opt(ts()),
    })
    post = p.table("post", key="post_id", mutable=True, doc="An original post and its cascade",
                   cols={
        "author_id": ref("user"),
        "created_at": ts(),
        "topic_id": ref("topic"),
        "virality": f64(min=0),
        "violation": hidden(cat(*POLICIES)),        # truth; written to labels/, not entities/
        "status": cat("open", "closed"),
        "labeled": boolean(),
        "reposts": i32(min=0), "replies": i32(min=0), "likes": i32(min=0),
        "exposed": i32(min=0), "max_depth": i16(min=0),
        "pending": i32(min=0),              # reaction timers not yet fired
        "last_activity": ts(),
        "capped": boolean(),                # a declared cap stopped the spread
    })

    p.owner("user", table="user", execution_owner=cfg.execution_owner, max_live=cfg.users)
    p.owner("cascade", table="post", execution_owner=cfg.cascade_execution_owner,
            max_live=c.max_live, created_by="user",            # creation message from the author
            retire_on=p.on_event("cascade_closed"))

    p.population(
        user, n=cfg.users,
        initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.97, 0.97, 1.0, 1.05, 1.15, 1.1),
                                    trend=0.001),
        attrs={
            "region": dist.categorical({"na": .22, "latam": .14, "eu": .2, "mena": .06,
                                        "africa": .06, "south_asia": .14, "east_asia": .12,
                                        "oceania": .06}),
            "client": dist.categorical({"ios": .42, "android": .43, "web": .15}),
            "acquisition": dist.categorical({"organic": .6, "search_ad": .1, "social_ad": .12,
                                             "referral": .14, "press": .04}),
        },
    )

    # Follow graph per epoch: degree-corrected generator with reciprocity at epoch 0, then each
    # rebuild applies the previous epoch's follow/unfollow events. Steps align to rebuilds.
    graph = std.graph_epochs(
        p, "follow_graph", nodes="user", every=g.epoch, align_steps=True,
        generator=std.graph.degree_corrected(out_degree=g.out_degree, in_weight=g.in_weight,
                                             reciprocity=g.reciprocity,
                                             homophily=("profile.interests", g.topic_homophily)),
        add_on="follow", remove_on="unfollow", src="user_id", dst="target_id",
        views=("followers", "following"),   # CSR both ways: fan-out and follow candidates
        emits="graph_epoch_built",
    )
    status = std.status_epochs(
        p, "account_status", key="user_id", every=g.status_epoch, align_steps=True,
        set_on="account_suspended",         # bitset: suspended as of the last rebuild
    )

    # ---------------------------------------------------------------- shards
    moderation = p.shard("moderation", key="queue", n=m.queues, doc="Review queue per group",
                         state={
        "q_post": "ref[post, max_queue]",   # FIFO ring of queued items (struct of arrays)
        "q_reply": "ref[reply, max_queue]",
        "q_user": "ref[user, max_queue]",
        "q_policy": "i8[max_queue]",        # hidden truth, carried in the report payload
        "q_reports": "i32[max_queue]",
        "q_first_at": "i64[max_queue]",
        "q_head": "i32", "q_len": "i32",
        "queued": "idmap[1024..max_queue]",  # (post, reply) -> ring slot, for duplicates
        "decided": "idset_ttl[1024..2000000]",  # decided items, forgotten after decided_ttl
        "strikes": "idmap[1024..1000000]",   # author -> upheld violations; -1 once suspended
        "tick_budget": "i32",
    }, params={"max_queue": m.max_queue}, route=std.hash_mod("reported_user_id", m.queues))

    report = p.request("report", frm="cascade", to="moderation", payload={
        "post_id": ref("post"), "reply_id": opt(ref("reply")), "reported_user_id": ref("user"),
        "reporter_id": ref("user"), "reason": cat(*POLICIES[1:], "other"),
        "policy": i16(),                    # hidden truth of the content (never exported)
    }, responses=("queued", "duplicate", "dropped"),
        latency=dist.shifted_lognormal(min_ms=1_000, median_ms=1_400))

    # Messages a partition does not wait for. Delivered at t + latency, and never before the next
    # step boundary, because the target may already have run ahead to the step end.
    p.message("moderation_action", frm="moderation", to="cascade", payload={
        "decision_id": ref("decision"), "decision": cat(*DECISIONS)},
        latency=dist.shifted_lognormal(min_s=5, median_s=30))
    p.message("suspend_account", frm="moderation", to="user", payload={
        "decision_id": ref("decision"), "policy": cat(*POLICIES[1:]), "strikes": i16()},
        latency=dist.shifted_lognormal(min_s=5, median_s=30))
    p.message("author_suspended", frm="user", to="cascade", delivery="next_step", payload={
        "decision_id": ref("decision")})                    # owner-to-owner: next step or later

    # ---------------------------------------------------------------- events
    common_user = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="An account is created", cols={
        **common_user, "region": cat(*REGIONS), "client": cat(*CLIENTS),
        "acquisition": cat(*ACQUISITION),
    })
    p.event("session_started", owner="user", cols={
        **common_user, "session_id": ref("session"), "client": cat(*CLIENTS),
    })
    p.event("post_created", owner="user", doc="An original post; its cascade starts here", cols={
        **common_user, "post_id": ref("post"), "session_id": opt(ref("session")),
        "topic_id": ref("topic"), "has_media": boolean(),
        "content_hash": i64(),              # normalized-text hash; templates collide
        "followers": i32(min=0),            # author's in-degree in the current graph epoch
    })
    p.event("follow", owner="user", doc="Takes effect in feeds at the next graph epoch", cols={
        **common_user, "target_id": ref("user"), "source": cat(*FOLLOW_SOURCES),
        "session_id": opt(ref("session")),
    })
    p.event("unfollow", owner="user", doc="Takes effect in feeds at the next graph epoch", cols={
        **common_user, "target_id": ref("user"), "session_id": opt(ref("session")),
    })
    p.event("account_suspended", owner="user", doc="Effective now for the account's own actions",
            cols={**common_user, "decision_id": ref("decision"), "policy": cat(*POLICIES[1:]),
                  "strikes": i16(min=1)})

    # Cascade events: emitted by the cascade owner, attributed to the acting user (referenced,
    # never mutated). author_id is the root author; via_user_id the account the viewer follows.
    common_cascade = {"user_id": ref("user"), "post_id": ref("post"), "author_id": ref("user")}
    p.event("impression_sampled", owner="cascade", doc="1-in-N sample of feed impressions", cols={
        **common_cascade, "via_user_id": ref("user"), "depth": i16(min=0),
        "sample_weight": i32(min=1),
    })
    p.event("like", owner="cascade", cols={
        **common_cascade, "via_user_id": ref("user"), "depth": i16(min=0),
    })
    p.event("reply", owner="cascade", cols={
        **common_cascade, "reply_id": ref("reply"), "parent_repost_id": opt(ref("repost")),
        "content_hash": i64(), "text_len": i16(min=1),
    })
    p.event("repost", owner="cascade", doc="Shows the root post to the reposter's followers", cols={
        **common_cascade, "repost_id": ref("repost"),
        "parent_repost_id": opt(ref("repost")),     # null: reposted from the root post
        "parent_user_id": ref("user"), "depth": i16(min=1), "lag_s": i32(min=0),
    })
    p.event("content_reported", owner="cascade", cols={
        **common_cascade, "report_id": ref("report"), "reply_id": opt(ref("reply")),
        "reported_user_id": ref("user"), "reason": cat(*POLICIES[1:], "other"),
    })
    p.event("cascade_closed", owner="cascade", doc="The cascade stops; its owner retires", cols={
        "post_id": ref("post"), "user_id": ref("user"),     # user_id: the root author
        "size": i32(min=1), "reposts": i32(min=0), "max_depth": i16(min=0),
        "likes": i32(min=0), "replies": i32(min=0), "exposed": i32(min=0),
        "reason": cat(*CLOSE_REASONS), "capped": boolean(),
    })
    p.event("moderation_decision", shard="moderation", doc="One decision per reported item", cols={
        "decision_id": ref("decision"), "queue": i16(),
        "user_id": ref("user"),             # the account whose content was reviewed
        "post_id": ref("post"), "reply_id": opt(ref("reply")),
        "decision": cat(*DECISIONS), "policy": cat(*POLICIES),
        "reports": i32(min=1), "first_reported_at": ts(), "wait_s": i32(min=0),
    })
    p.event("graph_epoch_built", source="follow_graph", doc="A new follow graph is in effect", cols={
        "epoch": i32(min=0), "nodes": i32(min=0), "edges": i64(min=0),
        "reciprocal_share": f64(min=0, max=1),
        "follows_applied": i32(min=0), "unfollows_applied": i32(min=0),
    })

    # ---------------------------------------------------------------- processes
    p.process("user_activity", owner="user", kernel=k.user_activity, config=a,
              start=p.on_created("user"),
              reads={"profile": profile, "topic": topic, "follow_graph": graph,
                     "account_status": status},
              commands=k.USER_COMMANDS)             # out.create_post is the creation message

    # Enforcement: a common shape, so a state machine. Not suppressed by overlays, so every
    # account, cohort members included, honors a suspension.
    e = p.machine("enforcement", owner="user", start=p.on_message("suspend_account"),
                  initial="suspending")
    e.state("suspending", branch={"suspended": (1.0, None, k.apply_suspension)})
    e.final("suspended")

    p.process("cascade", owner="cascade", kernel=k.cascade, config=c,
              start=p.on_created("post"),
              requests={"report": report},
              messages={"moderation_action": k.M_MODERATION, "author_suspended": k.M_AUTHOR_SUSPENDED},
              reads={"profile": profile, "topic": topic, "follow_graph": graph,
                     "account_status": status},
              commands=k.CASCADE_COMMANDS)

    p.process("moderation_intake", shard=moderation, kernel=k.moderation_intake, config=m,
              on_request=report)
    p.process("moderation_review", shard=moderation, kernel=k.moderation_review, config=m,
              every=m.review_tick)

    # ---------------------------------------------------------------- enrichment
    # Cross-owner features, computed after each step seals on canonical order; go to golden/
    p.feature("post_distinct_reposters_60s",
              std.rolling_distinct("user_id", by="post_id", window="60s"),
              on=["repost"], into="golden")
    p.feature("content_hash_distinct_users_24h",
              std.rolling_distinct("user_id", by="content_hash", window="24h"),
              on=["reply", "post_created"], into="golden")
    p.feature("user_follows_1h", std.rolling_count("follow", by="user_id", window="1h"),
              on=["follow"], into="golden")

    # ---------------------------------------------------------------- laws
    user_actions = ("session_started", "post_created", "follow", "unfollow")
    cascade_actions = ("impression_sampled", "like", "reply", "repost", "content_reported")

    p.check("chk.repost_parent_in_cascade",
            law.tree_parent("repost", node="repost_id", parent="parent_repost_id",
                            group="post_id", root="post_created"), required=True)
    p.check("chk.repost_once_per_user",
            law.at_most_once("repost", key=("post_id", "user_id")), required=True)
    p.check("chk.cascade_caps",
            law.count_le_cap("repost", cap=c.max_reposts, per="post_id")
            & law.range("repost.depth", min=1, max=c.max_depth), required=True)
    p.check("chk.suspended_silent",
            law.none_after("account_suspended", key="user_id", events=user_actions),
            required=True)
    p.check("chk.suspended_silent_in_feeds",
            law.none_after("account_suspended", key="user_id", events=cascade_actions,
                           grace=std.next_rebuild("account_status")), required=True)
    p.check("chk.decision_after_report",
            law.preceded_by("moderation_decision", by="content_reported",
                            key=("post_id", "reply_id")), required=True)
    p.check("chk.decision_once",
            law.at_most_once("moderation_decision", key=("post_id", "reply_id")), required=True)
    p.check("chk.follow_alternates",
            law.alternates(("follow", "unfollow"), key=("user_id", "target_id"),
                           initial=std.graph_edges("follow_graph", epoch=0)), required=True)
    p.check("chk.closed_cascade_silent",
            law.none_after("cascade_closed", key="post_id", events=cascade_actions),
            required=True)

    # ---------------------------------------------------------------- extension points
    # Named actions overlays may call (validate checks them against the resolved plan)
    p.expose(
        signup=k.signup, session=k.start_session, post=k.quick_post,
        follow=k.follow, unfollow=k.unfollow,
        amplify_repost=k.inject_repost, amplify_reply=k.inject_reply,
    )
    p.expose_param("moderation.strike_limit", m.strike_limit)

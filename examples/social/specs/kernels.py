"""Handwritten kernels for the social pack.

Every kernel follows the action interface:
    1. validate   read state, maybe reject(...)       no writes yet
    2. reserve    out.reserve(...) for every resource  RETRY if the slab is full
    3. commit     mutate state, emit, schedule         cannot fail
Random draws use ctx.rng.<dist>(site=N, ...); each draw site has its own number, so edits to
one site never shift draws at another. A site inside a loop is fine: draws at one site are
counted within an invocation.

Read inputs (ctx.reads.*) are immutable for the whole epoch: follow_graph (CSR, weekly),
account_status (suspended bitset, hourly), profile and topic (static). No kernel reads another
partition's mutable state; everything else arrives by request, response or message.
"""

import math

from neorisk_simkit.engine import COMMIT, RETRY, Local, Res, kernel, reject
from neorisk_simkit import std

# ------------------------------------------------------------------ command ids: user
C_START = 1             # on created: signup event, onboarding follows, first session
C_SESSION = 2           # timer: start the next session
C_POST = 3              # timer: write an original post inside a session
C_FOLLOW = 4            # timer: follow someone (candidate picked from the graph epoch)
C_UNFOLLOW = 5          # timer: unfollow someone currently followed
USER_COMMANDS = (C_START, C_SESSION, C_POST, C_FOLLOW, C_UNFOLLOW)

# ------------------------------------------------------------------ command ids: cascade
C_CASCADE_START = 30    # on created: first fan-out from the author, quiet and age timers
C_FANOUT = 31           # continuation: next 64 followers of one spreader
C_REACT = 32            # timer: one follower's delayed reaction to an exposure
C_QUIET = 33            # timer: close if nothing is pending
C_MAX_AGE = 34          # timer: close at the declared maximum age
R_QUEUED = 40           # response: report queued
R_DUPLICATE = 41        # response: item already queued or decided
R_DROPPED = 42          # response: queue full, report dropped
M_MODERATION = 50       # message: label or takedown decided by the moderation shard
M_AUTHOR_SUSPENDED = 51  # message: the author's account was suspended
CASCADE_COMMANDS = (C_CASCADE_START, C_FANOUT, C_REACT, C_QUIET, C_MAX_AGE,
                    R_QUEUED, R_DUPLICATE, R_DROPPED, M_MODERATION, M_AUTHOR_SUSPENDED)

# priorities at equal time (lower runs first); fan-out continuations before everything,
# then responses and messages, then own timers
PRIO_CONTINUE, PRIO_MESSAGE, PRIO_TIMER = 0, 1, 5

# reaction bits drawn at exposure time, carried by the C_REACT timer
A_IMPRESSION, A_LIKE, A_REPLY, A_REPOST, A_REPORT = 1, 2, 4, 8, 16

# indices into pack.POLICIES / DECISIONS / FOLLOW_SOURCES (cat codes are positional)
P_NONE, P_SPAM, P_ABUSE, P_MISINFO = 0, 1, 2, 3
D_NO_ACTION, D_LABEL, D_TAKEDOWN, D_SUSPEND = 0, 1, 2, 3
F_ONBOARDING, F_FOLLOW_BACK, F_FOF, F_POPULAR, F_TOPIC = 0, 1, 2, 3, 4

REJ_STALE = 1
REJ_INACTIVE = 2
REJ_NO_CANDIDATE = 3
REJ_CLOSED = 4
REJ_DUPLICATE = 5
REJ_CAP = 6
REJ_SUSPENDED = 7
REJ_EMPTY = 8

FANOUT = 64              # followers per fan-out sub-step (cfg.fanout_substep, fixed)
REVIEW_SUBSTEP = 64      # queue items per review sub-step
MAX_POSTS_PER_SESSION = 5
MAX_ONBOARDING = 20
LIVE_POSTS = 16          # recent cascades remembered per user for suspension notices
BAD_REPLIES = 16         # violating replies remembered per cascade as report targets
SECOND = 1_000_000       # µs
HOUR = 3_600_000_000

# Per-user scratch, laid out next to the user row; freed when the owner retires. Shared by every
# process of the user owner (user_activity, enforcement, the exposed post/follow actions).
USER_LOCAL = Local(
    session="ref",                      # current session id
    edges="idmap[8..256]",              # target -> (time, followed?) changes since the epoch
    live_post="ref[16]", live_head="i8",  # ring of recent cascades (post ids)
)

# Per-cascade scratch, next to the post row. Sets grow by size class up to their hard cap.
CASCADE_LOCAL = Local(
    seen="idset[64..250000]",           # exposed users: per-cascade dedup (cascade.max_exposed)
    reposters="idset[16..20000]",       # users who reposted (cascade.max_reposts)
    bad_reply="ref[16]", bad_author="ref[16]", bad_policy="i8[16]", bad_n="i8",
)


# ================================================================== user activity
@kernel(state="user", local=USER_LOCAL, commands=USER_COMMANDS,
        max=Res(records={"user_signed_up": 1, "session_started": 1, "post_created": 1,
                         "follow": 1, "unfollow": 1},
                creates={"post": 1}, timers=1 + MAX_ONBOARDING + MAX_POSTS_PER_SESSION))
def user_activity(ctx, s, loc, cmd, out):
    """One account's sessions, posts and follow changes. Dispatches on the command kind."""
    cfg = ctx.cfg
    if s.status != std.cat("active"):
        return reject(REJ_INACTIVE)                    # suspended: every pending timer drops
    if cmd.kind == C_START:
        return _start(ctx, s, loc, out, cfg)
    if cmd.kind == C_SESSION:
        return _session(ctx, s, loc, out, cfg)
    if cmd.kind == C_POST:
        return _post(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_FOLLOW:
        return _follow(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_UNFOLLOW:
        return _unfollow(ctx, s, loc, cmd, out, cfg)
    return reject(REJ_STALE)


def _start(ctx, s, loc, out, cfg):
    n = ctx.rng.dist(site=1, d=cfg.onboarding_follows)            # 3..20
    if not out.reserve(records={"user_signed_up": 1}, timers=n + 1):
        return RETRY
    out.emit_user_signed_up(ctx.t, user_id=ctx.self_id, region=s.region, client=s.client,
                            acquisition=s.acquisition)
    t = ctx.t
    for i in range(n):                                             # onboarding suggestions
        t += ctx.rng.exp_us(site=2, mean_s=20)
        out.timer(t, C_FOLLOW, prio=PRIO_TIMER, source=F_ONBOARDING, target=0)
    out.timer(t + ctx.rng.exp_us(site=3, mean_s=120), C_SESSION, prio=PRIO_TIMER)
    return COMMIT


def _session(ctx, s, loc, out, cfg):
    prof = ctx.reads.profile
    act = prof.activity[ctx.self_id]
    n_posts = min(MAX_POSTS_PER_SESSION,
                  ctx.rng.poisson(site=10, mean=cfg.posts_per_session * prof.poster[ctx.self_id]))
    follow = ctx.rng.bernoulli(site=11, p=cfg.follow_p)
    unfollow = ctx.rng.bernoulli(site=12, p=cfg.unfollow_p)
    if not out.reserve(records={"session_started": 1}, timers=1 + n_posts + 2):
        return RETRY
    loc.edges.prune_before(ctx.reads.follow_graph.built_at)        # now part of the graph
    loc.session = out.new_id("session")
    out.emit_session_started(ctx.t, user_id=ctx.self_id, session_id=loc.session, client=s.client)
    length = ctx.rng.dist_us(site=13, d=cfg.session_len)
    for i in range(n_posts):
        out.timer(ctx.t + ctx.rng.uniform_us(site=14, hi=length), C_POST, prio=PRIO_TIMER,
                  topic=-1, violation=-1, content_hash=0)
    if follow:
        out.timer(ctx.t + ctx.rng.uniform_us(site=15, hi=length), C_FOLLOW, prio=PRIO_TIMER,
                  source=-1, target=0)
    if unfollow:
        out.timer(ctx.t + ctx.rng.uniform_us(site=16, hi=length), C_UNFOLLOW, prio=PRIO_TIMER,
                  target=0)
    # Pareto gaps whose mean is 1/activity days, floored at session_gap_min_h
    a = cfg.session_gap_alpha
    min_h = max(cfg.session_gap_min_h, 24.0 * (a - 1.0) / (a * max(act, 1e-3)))
    out.timer(ctx.t + length + ctx.rng.pareto_us(site=17, alpha=a, min_h=min_h), C_SESSION,
              prio=PRIO_TIMER)
    return COMMIT


def _post(ctx, s, loc, cmd, out, cfg):
    """Write an original post: create its cascade owner (a creation message) and remember it."""
    if not out.reserve(records={"post_created": 1}, creates={"post": 1}):
        return RETRY
    prof = ctx.reads.profile
    topic = cmd.topic
    if topic < 0:                                                  # organic: one of my topics
        topic = prof.interests[ctx.self_id][ctx.rng.categorical(site=20, p=(.6, .28, .12))]
    violation = cmd.violation
    if violation < 0:
        violation = ctx.rng.categorical(site=21, p=cfg.violation_p)
    content_hash = cmd.content_hash
    if content_hash == 0:
        content_hash = ctx.rng.u63(site=22)                        # unique text
    post = out.create_post(author_id=ctx.self_id, created_at=ctx.t, topic_id=topic,
                           virality=0.0,       # drawn by the cascade at start, from its config
                           violation=violation, status=std.cat("open"),
                           labeled=False, reposts=0, replies=0, likes=0, exposed=0,
                           max_depth=0, pending=0, last_activity=ctx.t, capped=False)
    s.posts = std.checked_add(s.posts, 1)
    loc.live_post[loc.live_head] = post                            # oldest one falls off
    loc.live_head = (loc.live_head + 1) % LIVE_POSTS
    out.emit_post_created(ctx.t, user_id=ctx.self_id, post_id=post, session_id=loc.session,
                          topic_id=topic, has_media=ctx.rng.bernoulli(site=24, p=cfg.media_p),
                          content_hash=content_hash,
                          followers=ctx.reads.follow_graph.in_degree(ctx.self_id))
    return COMMIT


def _is_following(ctx, loc, v):
    """The epoch graph, overridden by this user's own changes since the epoch was built."""
    i = loc.edges.find(v)
    if i >= 0 and loc.edges.t[i] >= ctx.reads.follow_graph.built_at:
        return loc.edges.val[i] == 1
    return ctx.reads.follow_graph.has_edge(ctx.self_id, v)


def _following_count(ctx, loc):
    n = ctx.reads.follow_graph.out_degree(ctx.self_id)
    for i in loc.edges.slots():
        if loc.edges.t[i] >= ctx.reads.follow_graph.built_at:
            n += 1 if loc.edges.val[i] == 1 else -1
    return n


def _pick_candidate(ctx, source):
    """A follow candidate from the read inputs only. 0 when the chosen source has none."""
    g, me = ctx.reads.follow_graph, ctx.self_id
    if source == F_FOLLOW_BACK:
        return g.followers_pick(me, ctx.rng.uniform(site=30))
    if source == F_FOF:
        via = g.following_pick(me, ctx.rng.uniform(site=31))
        return g.following_pick(via, ctx.rng.uniform(site=32)) if via != 0 else 0
    if source == F_POPULAR:
        return g.sample_by_in_degree(ctx.rng.uniform(site=33))
    topic = ctx.reads.profile.interests[me][ctx.rng.uniform_int(site=34, lo=0, hi=2)]
    return ctx.reads.profile.sample_interested(topic, ctx.rng.uniform(site=35), by="influence")


def _follow(ctx, s, loc, cmd, out, cfg):
    source, v = cmd.source, cmd.target
    if v == 0:
        if source < 0:
            source = ctx.rng.categorical(site=36, p=cfg.follow_source_mix)
        v = _pick_candidate(ctx, F_TOPIC if source == F_ONBOARDING else source)
    if v == 0 or v == ctx.self_id or _is_following(ctx, loc, v):
        return reject(REJ_NO_CANDIDATE)
    if ctx.reads.account_status.suspended[v]:
        return reject(REJ_NO_CANDIDATE)
    if _following_count(ctx, loc) >= cfg.max_following or loc.edges.full():
        return reject(REJ_CAP)                                     # until the next epoch
    if not out.reserve(records={"follow": 1}):
        return RETRY
    loc.edges.put(v, t=ctx.t, val=1)
    out.emit_follow(ctx.t, user_id=ctx.self_id, target_id=v, source=source,
                    session_id=loc.session if source != F_ONBOARDING else 0)
    return COMMIT


def _unfollow(ctx, s, loc, cmd, out, cfg):
    v = cmd.target
    if v == 0:
        v = ctx.reads.follow_graph.following_pick(ctx.self_id, ctx.rng.uniform(site=40))
    if v == 0 or not _is_following(ctx, loc, v):
        return reject(REJ_NO_CANDIDATE)                            # alternation holds by this
    if loc.edges.full():
        return reject(REJ_CAP)
    if not out.reserve(records={"unfollow": 1}):
        return RETRY
    loc.edges.put(v, t=ctx.t, val=0)
    out.emit_unfollow(ctx.t, user_id=ctx.self_id, target_id=v, session_id=loc.session)
    return COMMIT


# Exposed variants: the same actions as standalone kernels, so overlays can call them for
# cohort members whose user_activity process is suppressed.
@kernel(state="user", local=USER_LOCAL, config="activity",
        max=Res(records={"post_created": 1}, creates={"post": 1}))
def post_now(ctx, s, loc, cmd, out):
    if s.status != std.cat("active"):
        return reject(REJ_INACTIVE)
    return _post(ctx, s, loc, cmd, out, ctx.cfg)


@kernel(state="user", local=USER_LOCAL, config="activity", max=Res(records={"follow": 1}))
def follow_now(ctx, s, loc, cmd, out):
    if s.status != std.cat("active"):
        return reject(REJ_INACTIVE)
    return _follow(ctx, s, loc, cmd, out, ctx.cfg)


@kernel(state="user", local=USER_LOCAL, config="activity", max=Res(records={"unfollow": 1}))
def unfollow_now(ctx, s, loc, cmd, out):
    if s.status != std.cat("active"):
        return reject(REJ_INACTIVE)
    return _unfollow(ctx, s, loc, cmd, out, ctx.cfg)


# ================================================================== enforcement (user owner)
@kernel(state="user", local=USER_LOCAL,
        max=Res(records={"account_suspended": 1}, messages=LIVE_POSTS))
def apply_suspension(ctx, s, loc, cmd, out):
    """A suspend_account message from a moderation shard (arrives next step or later).

    Effective at this commit for the account's own actions. Each live cascade the account
    started gets an author_suspended message; feed-driven actions stop at the next hourly
    account_status rebuild.
    """
    if s.status == std.cat("suspended"):
        return reject(REJ_DUPLICATE)
    if not out.reserve(records={"account_suspended": 1}, messages=LIVE_POSTS):
        return RETRY
    s.status = std.cat("suspended")
    s.suspended_at = ctx.t
    out.emit_account_suspended(ctx.t, user_id=ctx.self_id, decision_id=cmd.decision_id,
                               policy=cmd.policy, strikes=cmd.strikes)
    for i in range(LIVE_POSTS):
        if loc.live_post[i] != 0:                  # retired cascades drop it as a late message
            out.send_author_suspended(ctx.t, to=loc.live_post[i], decision_id=cmd.decision_id)
    return COMMIT


# ================================================================== cascade (owner per root post)
@kernel(state="post", local=CASCADE_LOCAL, commands=CASCADE_COMMANDS, substep=FANOUT,
        max=Res(records={"impression_sampled": 1, "like": 1, "reply": 1, "repost": 1,
                         "content_reported": 1, "cascade_closed": 1},
                timers=FANOUT + 2, requests=1))
def cascade(ctx, s, loc, cmd, out):
    """Spread of one original post down the follower graph. Dispatches on the command kind."""
    cfg = ctx.cfg
    if cmd.kind == C_FANOUT:
        return _fanout(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_REACT:
        return _react(ctx, s, loc, cmd, out, cfg)
    if cmd.kind == C_CASCADE_START:
        return _cascade_start(ctx, s, loc, out, cfg)
    if cmd.kind == C_QUIET:
        return _quiet(ctx, s, out, cfg)
    if cmd.kind == C_MAX_AGE:
        return _close(ctx, s, out, std.cat("max_age"))
    if cmd.kind == M_MODERATION:
        return _on_moderation(ctx, s, cmd, out)
    if cmd.kind == M_AUTHOR_SUSPENDED:
        return _close(ctx, s, out, std.cat("author_suspended"))
    if cmd.kind == R_QUEUED or cmd.kind == R_DUPLICATE or cmd.kind == R_DROPPED:
        return COMMIT                                  # nothing to do; counted in run stats
    return reject(REJ_STALE)


def _cascade_start(ctx, s, loc, out, cfg):
    if s.status != std.cat("open"):
        return reject(REJ_STALE)
    if not out.reserve(timers=3):
        return RETRY
    s.virality = (ctx.reads.topic.virality[s.topic_id]
                  * ctx.rng.dist(site=49, d=cfg.virality))          # content appeal
    loc.seen.add(s.author_id)                          # the author never sees their own post
    out.timer(ctx.t + std.us(cfg.quiet_after), C_QUIET, prio=PRIO_TIMER)
    out.timer(ctx.t + std.us(cfg.max_age), C_MAX_AGE, prio=PRIO_TIMER)
    out.continue_at(ctx.t, C_FANOUT, cursor=0, spreader=s.author_id, parent=0, depth=0)
    return COMMIT


def _fanout(ctx, s, loc, cmd, out, cfg):
    """Expose the next 64 followers of one spreader (root author or a reposter).

    Fixed sub-step: at most FANOUT followers per invocation, then a same-time continuation at
    top priority, so nothing else at this timestamp interleaves and results never depend on
    buffer sizes. A follower is marked seen only if they actually see it; a follower who
    doesn't may still see it later through another reposter.
    """
    if s.status != std.cat("open"):
        return reject(REJ_CLOSED)                      # taken down mid fan-out
    g = ctx.reads.follow_graph
    lo, hi = g.followers_range(cmd.spreader)
    start = lo + cmd.cursor
    stop = min(start + FANOUT, hi)
    if not out.reserve(timers=stop - start + 1):
        return RETRY
    author_infl = ctx.reads.profile.influence[s.author_id]
    capped = False
    for i in range(start, stop):
        v = g.followers[i]
        if loc.seen.contains(v) or ctx.reads.account_status.suspended[v]:
            continue                                   # per-cascade dedup; suspended accounts
        if loc.seen.full():
            capped = True                              # max_exposed reached: stop spreading
            break
        if not ctx.rng.bernoulli(site=50, p=_p_see(ctx, s, cfg, v, author_infl)):
            continue
        loc.seen.add(v)
        s.exposed = std.checked_add(s.exposed, 1)
        acts = _draw_reaction(ctx, s, cfg, cmd.depth)
        if acts == 0:
            continue
        lag = ctx.rng.dist_us(site=51, d=cfg.exposure_delay)       # >= 1 s
        out.timer(ctx.t + lag, C_REACT, prio=PRIO_TIMER, actor=v, spreader=cmd.spreader,
                  parent=cmd.parent, depth=cmd.depth, acts=acts, lag_s=lag // SECOND)
        s.pending = std.checked_add(s.pending, 1)
    if capped:
        s.capped = True
    elif stop < hi:
        out.continue_at(ctx.t, C_FANOUT, cursor=stop - lo, spreader=cmd.spreader,
                        parent=cmd.parent, depth=cmd.depth)    # same time, top priority
    return COMMIT


def _p_see(ctx, s, cfg, v, author_infl):
    """P(follower v sees the post): opens the app within the window x feed rank."""
    prof = ctx.reads.profile
    p_open = 1.0 - math.exp(-prof.activity[v] * cfg.see_window_h / 24.0)
    rank = 0.25 * (1.0 + cfg.influence_boost * math.log1p(author_infl))
    if std.contains3(prof.interests[v], s.topic_id):
        rank *= cfg.topic_boost
    return p_open * min(1.0, rank)


def _draw_reaction(ctx, s, cfg, depth):
    """Which actions this exposure leads to, as bits. depth: the spreader's depth (root = 0)."""
    damp = cfg.label_damping if s.labeled else 1.0
    acts = 0
    if ctx.rng.bernoulli(site=60, p=1.0 / cfg.impression_sample_every):
        acts |= A_IMPRESSION
    if ctx.rng.bernoulli(site=61, p=cfg.like_p * damp):
        acts |= A_LIKE
    if ctx.rng.bernoulli(site=62, p=cfg.reply_p):
        acts |= A_REPLY
    p_repost = cfg.repost_p * s.virality * damp * cfg.depth_decay ** depth
    if ctx.rng.bernoulli(site=63, p=min(1.0, p_repost)):
        acts |= A_REPOST
    p_report = cfg.report_p[s.violation] * ctx.reads.topic.report_propensity[s.topic_id]
    if ctx.rng.bernoulli(site=64, p=min(1.0, p_report)):
        acts |= A_REPORT
    return acts


def _react(ctx, s, loc, cmd, out, cfg):
    """A follower acts on an exposure, after its delay. Emits attributed to that follower."""
    if s.status != std.cat("open"):
        return reject(REJ_CLOSED)
    v, acts, capped = cmd.actor, cmd.acts, False
    if ctx.reads.account_status.suspended[v]:
        acts = 0                                       # suspended since the exposure
    if acts & A_REPOST:
        if loc.reposters.contains(v):
            acts &= ~A_REPOST                          # reposted already (e.g. amplified)
        elif (s.reposts >= cfg.max_reposts or cmd.depth + 1 > cfg.max_depth
              or loc.reposters.full()):
            acts &= ~A_REPOST                          # declared caps: no further spread
            capped = True
    if acts & A_REPLY and s.replies >= cfg.max_replies:
        acts &= ~A_REPLY
    report_bad = -1
    if acts & A_REPORT and loc.bad_n > 0:
        # a violating reply is a likelier target than a clean root post
        w_root = 1.0 if s.violation != P_NONE else 0.1
        if ctx.rng.bernoulli(site=70, p=loc.bad_n / (loc.bad_n + w_root)):
            report_bad = ctx.rng.uniform_int(site=71, lo=0, hi=loc.bad_n - 1)
    if not out.reserve(records={"impression_sampled": 1, "like": 1, "reply": 1, "repost": 1,
                                "content_reported": 1}, requests=1, timers=1):
        return RETRY
    s.pending = std.checked_sub(s.pending, 1)
    s.capped = s.capped or capped
    if acts == 0:
        return COMMIT
    s.last_activity = ctx.t
    me, root, author = v, ctx.self_id, s.author_id
    if acts & A_IMPRESSION:
        out.emit_impression_sampled(ctx.t, user_id=me, post_id=root, author_id=author,
                                    via_user_id=cmd.spreader, depth=cmd.depth,
                                    sample_weight=cfg.impression_sample_every)
    if acts & A_LIKE:
        s.likes = std.checked_add(s.likes, 1)
        out.emit_like(ctx.t, user_id=me, post_id=root, author_id=author,
                      via_user_id=cmd.spreader, depth=cmd.depth)
    if acts & A_REPLY:
        reply = out.new_id("reply")
        s.replies = std.checked_add(s.replies, 1)
        out.emit_reply(ctx.t, user_id=me, post_id=root, author_id=author, reply_id=reply,
                       parent_repost_id=cmd.parent, content_hash=ctx.rng.u63(site=72),
                       text_len=1 + ctx.rng.geometric(site=73, mean=60, max=279))
        if ctx.rng.bernoulli(site=74, p=cfg.reply_abuse_p):
            _remember_bad_reply(loc, reply, me, P_ABUSE)
    if acts & A_REPOST:
        _repost(ctx, s, loc, out, me, cmd.spreader, cmd.parent, cmd.depth + 1, cmd.lag_s)
    if acts & A_REPORT:
        _report(ctx, s, loc, out, me, report_bad)
    return COMMIT


def _repost(ctx, s, loc, out, actor, parent_user, parent, depth, lag_s):
    """Record a repost node and start fan-out to the reposter's followers. After reserve."""
    rid = out.new_id("repost")
    loc.reposters.add(actor)
    loc.seen.add_if_room(actor)
    s.reposts = std.checked_add(s.reposts, 1)
    s.max_depth = max(s.max_depth, depth)
    out.emit_repost(ctx.t, user_id=actor, post_id=ctx.self_id, author_id=s.author_id,
                    repost_id=rid, parent_repost_id=parent,       # 0 -> null: from the root
                    parent_user_id=parent_user, depth=depth, lag_s=lag_s)
    out.continue_at(ctx.t, C_FANOUT, cursor=0, spreader=actor, parent=rid, depth=depth)


def _report(ctx, s, loc, out, reporter, bad):
    """File a report against the root post or a remembered violating reply. After reserve."""
    if bad >= 0:
        reply, target, policy = loc.bad_reply[bad], loc.bad_author[bad], loc.bad_policy[bad]
    else:
        reply, target, policy = 0, s.author_id, s.violation
    # The reporter's stated reason matches the hidden policy most of the time
    if policy == P_NONE:
        reason = ctx.rng.categorical(site=80, p=(.25, .25, .2, .3))    # spam/abuse/misinfo/other
    else:
        reason = policy - 1 if ctx.rng.bernoulli(site=81, p=0.8) else 3
    report = out.new_id("report")
    out.emit_content_reported(ctx.t, user_id=reporter, post_id=ctx.self_id, author_id=s.author_id,
                              report_id=report, reply_id=reply, reported_user_id=target,
                              reason=reason)
    # Immutable payload; routed by reported_user_id to one moderation shard (declared there)
    out.request_report(ctx.t, post_id=ctx.self_id, reply_id=reply, reported_user_id=target,
                       reporter_id=reporter, reason=reason, policy=policy)


def _remember_bad_reply(loc, reply, author, policy):
    i = loc.bad_n if loc.bad_n < BAD_REPLIES else reply % BAD_REPLIES   # overwrite when full
    loc.bad_reply[i], loc.bad_author[i], loc.bad_policy[i] = reply, author, policy
    loc.bad_n = min(loc.bad_n + 1, BAD_REPLIES)


def _quiet(ctx, s, out, cfg):
    if s.status != std.cat("open"):
        return reject(REJ_STALE)
    quiet = std.us(cfg.quiet_after)
    if s.pending == 0 and ctx.t >= s.last_activity + quiet:
        return _close(ctx, s, out, std.cat("quiet"))
    if not out.reserve(timers=1):
        return RETRY
    out.timer(max(ctx.t, s.last_activity) + quiet, C_QUIET, prio=PRIO_TIMER)
    return COMMIT


def _on_moderation(ctx, s, cmd, out):
    if cmd.decision == D_LABEL:
        if s.labeled or s.status != std.cat("open"):
            return reject(REJ_STALE)
        if not out.reserve():
            return RETRY
        s.labeled = True                               # damps reposts and likes from now on
        return COMMIT
    return _close(ctx, s, out, std.cat("takedown"))    # takedown or suspend_author


def _close(ctx, s, out, reason):
    if s.status != std.cat("open"):
        return reject(REJ_CLOSED)
    if not out.reserve(records={"cascade_closed": 1}):
        return RETRY
    s.status = std.cat("closed")
    out.emit_cascade_closed(ctx.t, post_id=ctx.self_id, user_id=s.author_id,
                            size=1 + s.reposts, reposts=s.reposts, max_depth=s.max_depth,
                            likes=s.likes, replies=s.replies, exposed=s.exposed,
                            reason=reason, capped=s.capped)
    return COMMIT                                      # owner retires on cascade_closed


# Exposed to overlays: inject an amplifying repost or reply into a cascade. Legal only when the
# caller runs in the same partition as the cascade (an overlay's campaign owner carries its
# members' cascades), so this is a same-partition action, not a cross-owner write.
@kernel(state="post", local=CASCADE_LOCAL, config="cascade",
        max=Res(records={"repost": 1}, timers=1))
def inject_repost(ctx, s, loc, cmd, out):
    cfg, v = ctx.cfg, cmd.actor
    if s.status != std.cat("open"):
        return reject(REJ_CLOSED)
    if v == s.author_id or loc.reposters.contains(v):
        return reject(REJ_DUPLICATE)
    if s.reposts >= cfg.max_reposts or loc.reposters.full():
        return reject(REJ_CAP)
    if ctx.reads.account_status.suspended[v]:
        return reject(REJ_SUSPENDED)
    if not out.reserve(records={"repost": 1}, timers=1):
        return RETRY
    s.last_activity = ctx.t
    _repost(ctx, s, loc, out, v, s.author_id, 0, 1, (ctx.t - s.created_at) // SECOND)
    return COMMIT


@kernel(state="post", local=CASCADE_LOCAL, config="cascade", max=Res(records={"reply": 1}))
def inject_reply(ctx, s, loc, cmd, out):
    cfg, v = ctx.cfg, cmd.actor
    if s.status != std.cat("open"):
        return reject(REJ_CLOSED)
    if s.replies >= cfg.max_replies:
        return reject(REJ_CAP)
    if ctx.reads.account_status.suspended[v]:
        return reject(REJ_SUSPENDED)
    if not out.reserve(records={"reply": 1}):
        return RETRY
    reply = out.new_id("reply")
    s.replies = std.checked_add(s.replies, 1)
    s.last_activity = ctx.t
    out.emit_reply(ctx.t, user_id=v, post_id=ctx.self_id, author_id=s.author_id, reply_id=reply,
                   parent_repost_id=0, content_hash=cmd.content_hash, text_len=cmd.text_len)
    if cmd.policy != P_NONE:
        _remember_bad_reply(loc, reply, v, cmd.policy)
    return COMMIT


# ================================================================== moderation shard
@kernel(state="moderation", config="moderation", max=Res(messages=1))
def moderation_intake(ctx, s, cmd, out):
    """A report request. Answers queued / duplicate / dropped; decisions come later."""
    item = std.pair_key(cmd.post_id, cmd.reply_id)
    decided = s.decided.contains(item)
    slot = s.queued.find(item)
    if not out.reserve(messages=1):
        return RETRY
    if decided or slot >= 0:
        if slot >= 0:
            s.q_reports[slot] = std.checked_add(s.q_reports[slot], 1)
        out.respond(cmd, "duplicate")
        return COMMIT
    if s.q_len >= ctx.cfg.max_queue:
        out.respond(cmd, "dropped")                    # counted; never decided
        return COMMIT
    slot = (s.q_head + s.q_len) % ctx.cfg.max_queue
    s.q_post[slot], s.q_reply[slot], s.q_user[slot] = cmd.post_id, cmd.reply_id, cmd.reported_user_id
    s.q_policy[slot], s.q_reports[slot], s.q_first_at[slot] = cmd.policy, 1, ctx.t
    s.q_len += 1
    s.queued.put(item, slot)
    out.respond(cmd, "queued")
    return COMMIT


@kernel(state="moderation", config="moderation", substep=REVIEW_SUBSTEP,
        max=Res(records={"moderation_decision": REVIEW_SUBSTEP}, messages=2 * REVIEW_SUBSTEP,
                timers=1))
def moderation_review(ctx, s, cmd, out):
    """Reviewers work the queue FIFO. Runs every review_tick; 64 items per sub-step.

    The tick's capacity is drawn once (cursor 0) from the hourly rate and a day/night curve,
    then sub-steps continue at the same time, top priority, until it is used or the queue empty.
    """
    cfg = ctx.cfg
    if cmd.cursor == 0:
        budget = ctx.rng.poisson(site=1, mean=_tick_capacity(ctx, cfg))
    else:
        budget = s.tick_budget
    n = min(REVIEW_SUBSTEP, budget - cmd.cursor, s.q_len)
    if n <= 0:
        return reject(REJ_EMPTY)
    if not out.reserve(records={"moderation_decision": n}, messages=2 * n, timers=1):
        return RETRY
    s.tick_budget = budget
    for j in range(n):
        slot = s.q_head
        post, reply, author = s.q_post[slot], s.q_reply[slot], s.q_user[slot]
        policy = s.q_policy[slot]
        decision, decided_policy = D_NO_ACTION, P_NONE
        if ctx.rng.bernoulli(site=2, p=cfg.action_p[policy]):
            decision = D_LABEL if ctx.rng.bernoulli(site=3, p=cfg.label_share[policy]) else D_TAKEDOWN
            decided_policy = policy if policy != P_NONE else 1 + ctx.rng.categorical(
                site=4, p=(.5, .3, .2))                # false positive: some policy is cited
        strikes = 0
        if decision == D_TAKEDOWN:
            strikes = s.strikes.get(author, 0)
            if strikes >= 0:                           # -1: already suspended
                strikes += 1
                if strikes >= cfg.strike_limit:
                    decision = D_SUSPEND
                s.strikes.put(author, -1 if decision == D_SUSPEND else strikes)
        did = out.new_id("decision")
        out.emit_moderation_decision(ctx.t, decision_id=did, queue=ctx.self_id, user_id=author,
                                     post_id=post, reply_id=reply, decision=decision,
                                     policy=decided_policy, reports=s.q_reports[slot],
                                     first_reported_at=s.q_first_at[slot],
                                     wait_s=(ctx.t - s.q_first_at[slot]) // SECOND)
        if reply == 0 and decision != D_NO_ACTION:     # the cascade labels itself or closes
            out.send_moderation_action(ctx.t, to=post, decision_id=did, decision=decision)
        if decision == D_SUSPEND:
            out.send_suspend_account(ctx.t, to=author, decision_id=did,
                                     policy=decided_policy - 1,   # POLICIES[1:] code
                                     strikes=strikes)
        item = std.pair_key(post, reply)
        s.queued.remove(item)
        s.decided.add(item, t=ctx.t)                   # forgotten after decided_ttl
        s.q_head = (s.q_head + 1) % cfg.max_queue
        s.q_len -= 1
    if cmd.cursor + n < budget and s.q_len > 0:
        out.continue_at(ctx.t, cursor=cmd.cursor + n)  # same time, top priority
    return COMMIT


def _tick_capacity(ctx, cfg):
    """Expected reviews this tick: hourly rate x tick length x day/night curve (trough 03:00)."""
    h = std.hour_of_day(ctx.t)
    night = cfg.night_capacity
    curve = night + (1.0 - night) * 0.5 * (1.0 - math.cos(2.0 * math.pi * (h - 3.0) / 24.0))
    return cfg.reviews_per_hour * ctx.every_s / 3600.0 * curve


# Thin actions exposed to overlays. Each is a std recipe bound to this pack's events.
signup = std.action.emit_signup("user_signed_up")
start_session = std.action.timer(C_SESSION)
quick_post = post_now                                  # params: topic, violation, content_hash
follow = follow_now                                    # params: target, source
unfollow = unfollow_now                                # params: target

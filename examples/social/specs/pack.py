"""A social network: a follow graph and repost cascades.

The follow graph is built once (degree-corrected: popular accounts attract followers, and
some follows are reciprocated) and shared read-only as adjacency arrays. Users post at a
steady rate. Each post creates a cascade owner that holds everything about that post: its
followers see it after a delay, some like it, some repost it, and a repost exposes the
reposter's followers in turn. Each user sees a cascade at most once and reposts it at most
once (per-cascade dedup); a cascade stops at a size cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from neorisk_simkit.checks import laws
from neorisk_simkit.engine import DAY, HOUR
from neorisk_simkit.spec import Latency, Pack, cat, i32, i64, ref

NAME = "social"


@dataclass
class Config:
    users: int = 1500
    follows_mean: float = 25.0
    popularity_alpha: float = 1.6     # Pareto tail of popularity
    reciprocity: float = 0.25
    posts_per_day: float = 0.12
    view_p: float = 0.35
    like_p: float = 0.15
    repost_p: float = 0.06
    view_delay_h: float = 3.0
    max_cascade: int = 400


@dataclass
class User:
    uid: int = 0


@dataclass
class Cascade:
    root: int = 0                     # the post id
    author: int = 0
    seen: set[int] = field(default_factory=set)
    reposted: set[int] = field(default_factory=set)
    size: int = 0


def define(p: Pack) -> None:
    p.entity("users", key="user_id", cols={"tier": cat("regular", "popular")})
    p.entity("follows", key="follow_id", cols={"follower_id": ref("users"),
                                               "followee_id": ref("users")})
    p.event("post_created", cols={"post_id": i64(), "user_id": ref("users")})
    p.event("post_viewed", cols={"post_id": i64(), "user_id": ref("users"),
                                 "via_post": i64(doc="The post or repost that exposed it")})
    p.event("post_liked", cols={"post_id": i64(), "user_id": ref("users")})
    p.event("post_reposted", cols={"post_id": i64(doc="The cascade's root post"),
                                   "repost_id": i64(), "user_id": ref("users"),
                                   "parent_id": i64(), "parent_user": ref("users"),
                                   "depth": i32(min=1)})

    user = p.owner("user", state=User, latency=Latency(0.05, 0.3))
    cascade = p.owner("cascade", state=Cascade, latency=Latency(0.05, 0.3))
    posting = user.process("posting", start="start")
    spread = cascade.process("spread", start="publish")

    @posting.action
    def start(ctx, s, cmd):
        ctx.after(ctx.rng.exponential(DAY / ctx.cfg.posts_per_day), "post")

    @posting.action
    def post(ctx, s, cmd):
        ctx.create("cascade", author=s.uid)
        ctx.after(ctx.rng.exponential(DAY / ctx.cfg.posts_per_day), "post")

    def expose(ctx, s, who: int, via: int, depth: int) -> None:
        g, rng, cfg = ctx.shared.graph, ctx.rng, ctx.cfg
        fans = g.followers[g.offsets[who - 1]:g.offsets[who]]
        for f in fans:                                 # fan-out is a loop
            if rng.random() < cfg.view_p:
                ctx.after(rng.exponential(cfg.view_delay_h * HOUR), "view", viewer=int(f),
                          via=via, via_user=who, depth=depth)

    @spread.action
    def publish(ctx, s, cmd):
        s.root = ctx.new_id("post")
        ctx.emit("post_created", post_id=s.root, user_id=s.author)
        s.seen.add(s.author)
        expose(ctx, s, s.author, s.root, 1)

    @spread.action
    def view(ctx, s, cmd):
        cfg, rng = ctx.cfg, ctx.rng
        if cmd.viewer in s.seen or s.size >= cfg.max_cascade:
            return ctx.reject("already_seen" if cmd.viewer in s.seen else "cascade_cap")
        s.seen.add(cmd.viewer)
        s.size += 1
        ctx.emit("post_viewed", post_id=s.root, user_id=cmd.viewer, via_post=cmd.via)
        if rng.random() < cfg.like_p:
            ctx.emit("post_liked", post_id=s.root, user_id=cmd.viewer)
        if cmd.viewer not in s.reposted and rng.random() < cfg.repost_p:
            s.reposted.add(cmd.viewer)
            rid = ctx.new_id("post")
            ctx.emit("post_reposted", post_id=s.root, repost_id=rid, user_id=cmd.viewer,
                     parent_id=cmd.via, parent_user=cmd.via_user, depth=cmd.depth)
            expose(ctx, s, cmd.viewer, rid, cmd.depth + 1)

    # --- laws ---------------------------------------------------------------------------
    p.check("one_view_per_user_and_post", laws.unique("post_viewed", ["post_id", "user_id"]))
    p.check("one_repost_per_user_and_post", laws.unique("post_reposted", ["post_id",
                                                                          "user_id"]))
    p.check("reposts_follow_their_parent", _parents)
    p.check("viewers_follow_who_exposed_them", _edges, group="cross")

    @p.source
    def graph(src):
        cfg, rng = src.cfg, src.rng
        n = cfg.users
        pop = rng.pareto(cfg.popularity_alpha, n) + 1.0
        ids = [src.insert("users", tier="popular" if x > 6 else "regular") for x in pop]
        w = pop / pop.sum()
        edges: set[tuple[int, int]] = set()
        for u in range(n):
            k = rng.poisson(cfg.follows_mean)
            for v in rng.choice(n, size=min(k, n - 1), replace=False, p=w):
                if v != u:
                    edges.add((u, int(v)))
                    if rng.random() < cfg.reciprocity:
                        edges.add((int(v), u))
        e = np.array(sorted(edges, key=lambda x: (x[1], x[0])), dtype=np.int64)
        for a, b in e:
            src.insert("follows", follower_id=ids[a], followee_id=ids[b])
        # followers of user id i (1-based): followers[offsets[i-1]:offsets[i]]
        counts = np.bincount(e[:, 1], minlength=n)
        src.share("graph", followers=np.array(ids)[e[:, 0]],
                  offsets=np.concatenate([[0], np.cumsum(counts)]))
        for i in ids:
            src.create("user", at=float(rng.uniform(0, HOUR)), uid=i)


CITE = ("partition_id", "seq", "action_id")


def _parents(d):
    """A repost's parent is its root or an earlier repost in the same cascade, one level up."""
    posts = d.ev("post_created").select(pl.col("post_id").alias("parent_id"),
                                        pl.col("post_id").alias("root"),
                                        pl.col("seq").alias("pseq"), pl.lit(0, pl.Int64).alias("pdepth"))
    reps = d.ev("post_reposted").select(pl.col("repost_id").alias("parent_id"),
                                        pl.col("post_id").alias("root"),
                                        pl.col("seq").alias("pseq"),
                                        pl.col("depth").cast(pl.Int64).alias("pdepth"))
    r = d.ev("post_reposted").join(pl.concat([posts, reps]), on="parent_id", how="left")
    bad = r.filter(pl.col("root").is_null() | (pl.col("root") != pl.col("post_id"))
                   | (pl.col("pseq") >= pl.col("seq"))
                   | (pl.col("depth") != pl.col("pdepth") + 1))
    return r.height, bad.select(*CITE, pl.lit("bad repost parent").alias("detail"))


def _edges(d):
    """Every view came through a follow edge: the viewer follows the user who exposed it."""
    f = d.entities["follows"].select(pl.col("follower_id").alias("user_id"),
                                     pl.col("followee_id").alias("exposer"), pl.lit(1).alias("e"))
    src = pl.concat([
        d.ev("post_created").select(pl.col("post_id").alias("via_post"),
                                    pl.col("user_id").alias("exposer")),
        d.ev("post_reposted").select(pl.col("repost_id").alias("via_post"),
                                     pl.col("user_id").alias("exposer"))])
    v = (d.ev("post_viewed").join(src, on="via_post", how="left")
         .join(f, on=["user_id", "exposer"], how="left"))
    bad = v.filter(pl.col("e").is_null())
    return v.height, bad.select(*CITE, pl.lit("view without a follow edge").alias("detail"))

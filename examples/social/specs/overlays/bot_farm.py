"""Bot farm: coordinated accounts that inflate a few promoted accounts.

A campaign is one operator, 1-3 promoted (target) accounts and a burst of 20-300 bots, all under
one campaign owner (execution_owner="campaign_id"). The campaign owner also carries the cascades
its members start (carry_owners=("cascade",)), so when a target posts, its bots can repost and
reply into that cascade within seconds as same-partition actions: no cross-owner writes, no
messages to wait for. Campaigns run in parallel.

What the base population feels (reported as interference):
    - bots' follows change the follow graph from the next weekly epoch for everyone;
    - reports on promoted posts and templated replies take moderation capacity from the same
      queues ordinary reports use, so ordinary decisions wait longer.

    datagen run examples/social --profile full --overlay bot_farm \
        --set bot_farm.size=60 --set bot_farm.amplify_p=0.9
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          size: int = 40,                                       # campaigns (operators)
          bots: dist.Dist = dist.negbinom(mean=80, disp=0.6, min=20, max=300),
          targets: dist.Dist = dist.uniform_int(1, 3),          # promoted accounts per campaign
          arrive: dist.Dist = dist.burst(start="day 7", span="60d"),
          burst_stagger: dist.Dist = dist.exp(mean_s=45),       # bots created seconds apart
          mutual_follow_p: float = 0.5,                         # bot follows a fellow bot
          cover_follows: dist.Dist = dist.geometric(mean=15, max=60),   # popular accounts
          warmup: str = "2d",                                   # before targets start posting
          post_gap: dist.Dist = dist.lognormal(median_s=14_400, sigma=0.8),
          promo_topics: dist.Dist = dist.categorical({"crypto": .5, "finance": .3,
                                                      "politics": .2}),
          spam_p: float = 0.7,                                  # promoted posts that violate
          amplify_p: float = 0.8,                               # bot reposts a promoted post
          amplify_delay: dist.Dist = dist.shifted_lognormal(min_s=2, median_s=10, sigma=0.7),
          reply_p: float = 0.35,                                # bot adds a templated reply
          reply_delay: dist.Dist = dist.shifted_lognormal(min_s=5, median_s=40, sigma=0.8),
          templates: int = 6,                                   # reply texts per campaign
          campaign_life: str = "45d") -> None:

    camp = o.cohort("bot_farm", table="user", size=size, arrivals=arrive,
                    execution_owner="campaign_id",              # operator + targets + bots
                    carry_owners=("cascade",),                  # ... and their cascades
                    suppress=["user_activity"],                 # no organic sessions or posts
                    attrs={"acquisition": dist.categorical({"organic": .7, "social_ad": .3}),
                           "client": dist.categorical({"android": .65, "web": .35}),
                           "profile.activity": dist.lognormal(median=6.0, sigma=0.3),
                           "profile.poster": 0.0})
    tpl = std.template_pool(n=templates, per="campaign", text_len=dist.uniform_int(40, 140))

    # ---------------------------------------------------------------- operator
    op = o.machine("operator", members=camp, initial="new")
    op.state("new", branch={"spawning": (
        1.0, dist.lognormal(median_s=600),
        o.base.signup.then(std.spawn_members("target", n=targets))
                     .then(std.spawn_members("bot", n=bots, stagger=burst_stagger)))})
    op.state("spawning", join={"running": ("bot_ready", "all_spawned")},
             timer={"running": "6h"}, late="ignore")
    op.state("running", timer={"retired": campaign_life})
    op.final("retired")

    # ---------------------------------------------------------------- promoted accounts
    t = o.machine("target", members=camp.spawned("target"), initial="new")
    t.state("new", branch={"warming": (1.0, dist.exp(mean_s=300), o.base.signup)})
    t.state("warming", timer={"promoting": warmup})
    t.state("promoting",
            repeat=(post_gap, 1.0,
                    o.base.post.with_params(topic=promo_topics,
                                            violation=dist.categorical({"spam": spam_p,
                                                                        "none": 1 - spam_p}))
                    .then(std.broadcast_members("bot", "target_posted", post="last_post"))),
            until=std.status("suspended"), then="gone")
    t.final("gone")

    # ---------------------------------------------------------------- bots
    plan = std.follow_plan(first=camp.spawned("target"),               # every promoted account
                           peers=camp.spawned("bot"), peer_share=mutual_follow_p,
                           cover=std.popular("follow_graph", n=cover_follows),
                           shuffle=True)
    b = o.machine("bot", members=camp.spawned("bot"), initial="new")
    b.state("new", branch={"following": (1.0, dist.exp(mean_s=30), o.base.signup)})
    b.state("following",
            repeat=(dist.exp(mean_s=20), 1.0,
                    o.base.follow.with_params(target=plan.next, source=plan.source)),
            until=plan.done, then="ready")              # follows take effect next epoch
    b.state("ready", branch={"idle": (1.0, None, std.send_parent("bot_ready"))})
    b.state("idle", on_message={"target_posted": "amplifying"},
            until=std.status("suspended"), then="gone")
    b.state("amplifying", branch={
        "replying": (amplify_p, amplify_delay,
                     o.base.amplify_repost.with_params(post=std.msg("post"), actor="self")),
        "idle": (1 - amplify_p, None, None),
    })
    b.state("replying", branch={"idle": (1.0, reply_delay, std.maybe(
        reply_p, o.base.amplify_reply.with_params(post=std.msg("post"), actor="self",
                                                  content_hash=tpl.hash,
                                                  text_len=tpl.text_len, policy="spam")))})
    b.final("gone")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(camp, role={"operator", "target", "bot"}, outcome=("active", "suspended"),
            available_at=std.after("account_suspended", dist.gamma(mean_days=2),
                                   otherwise=std.after("user_signed_up",
                                                       dist.gamma(mean_days=60))))

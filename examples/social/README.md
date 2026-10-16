# Social network (microblogging)

Accounts sign up, open the app in sessions, follow and unfollow each other, and write short
posts. Each original post grows a cascade: followers see it after a delay and may like, reply,
repost (carrying it to their own followers) or report it. Reports go to moderation queues that
label, take down, or suspend repeat offenders. See [`specs/brief.md`](specs/brief.md).

## Model

| Partition | Kind | Holds | Processes |
|---|---|---|---|
| `user` | owner | profile, status, post count; scratch: current session, own follow changes since the epoch, recent cascades | `user_activity` (kernel), `enforcement` (machine) |
| `cascade` | owner, one per original post | the root post (hidden policy, virality, label) and its spread: counts, pending reactions, dedup set of exposed users, set of reposters | `cascade` (kernel, 64-follower fan-out sub-steps) |
| `moderation` × 4 | shard, routed by reported author | FIFO review queue, queued and decided items, author strikes | `moderation_intake` (on request), `moderation_review` (kernel, every 5 min, 64-item sub-steps) |

| Read input | Rebuilt | Built from |
|---|---|---|
| `follow_graph` | weekly (`graph.epoch`) | epoch 0: degree-corrected generator with reciprocity and topic homophily; then the previous graph plus that week's `follow` / `unfollow` events. CSR in both directions |
| `account_status` | hourly (`graph.status_epoch`) | bitset of accounts with an `account_suspended` event |
| `profile`, `topic` | never | static population attributes (activity, influence, posting propensity, interests); topic virality and report propensity |

Rebuilds happen at step boundaries the engine aligns to, from sealed events only, so a rebuild
reads nothing mutable and gives the same result at any step length or thread count.

**Cascade.** Posting creates the `cascade` owner with a creation message; it starts in the next
round of the same step. The cascade walks the author's followers in the current graph, 64 per
sub-step, continuing at the same time at top priority. Each follower who sees the post (activity
× feed rank: author influence, topic match) is added to the cascade's dedup set, and the
reactions they will have are drawn at once and scheduled as one timer after a log-normal delay
(≥ 1 s, median 45 min). When a repost fires, the cascade records the node (`repost_id`, parent,
depth, lag) and starts the same fan-out from the reposter. Every event is emitted by the cascade
owner and attributed to the acting user by `user_id`; no user row is written. Declared caps
(depth 40, 20,000 reposts, 250,000 exposed) stop spreading and are checked as laws. The cascade
closes when nothing has been pending for 12 h, at 7 days, on a takedown, or when its author is
suspended; it then retires.

**Moderation.** A report is a request from the cascade to the author's moderation shard
(δ = 1 s). The shard answers `queued`, `duplicate` (adds to the item's report count) or
`dropped` (queue full). Every 5 minutes reviewers draw a capacity from the hourly rate and a
day/night curve and decide items FIFO: `no_action`, `label`, `takedown`, or `suspend_author` at
the third upheld violation. Label and takedown reach the cascade as a `moderation_action`
message; suspension reaches the author's `user` owner as `suspend_account`. Both are one-way
messages delivered at the next step boundary or later (the target may have run ahead).

**Suspension.** `enforcement` emits `account_suspended`, which is effective immediately for the
account's own actions (every `user_activity` command checks status), and sends
`author_suspended` to each recent cascade the account started, which close. Actions the account
would take as a follower inside other cascades stop at the next hourly `account_status`
rebuild; `chk.suspended_silent_in_feeds` checks exactly that grace.

**Follows.** `follow` and `unfollow` are recorded at once but shape feeds from the next weekly
epoch. A user keeps their own changes since the last rebuild in scratch, so they never follow
twice or unfollow someone they don't follow. Follow-backs come from the weekly graph's follower
list; follow-back triggered by an individual follow event, and deduplicating one person's
exposure across cascades, are out of v1 (design doc, Domain stress tests).

**Why engagement lives in the cascade.** A user owner can't see what is in its feed without
reading cascade state or receiving one message per exposure. Making the root post's cascade
the owner of exposure, likes, replies, reposts and reports keeps all of a post's engagement
in one partition (parent IDs, dedup and caps are exact) and needs only the read-only graph.
The cost: engagement isn't tied to a `session_id`.

**Events (14):** `user_signed_up`, `session_started`, `post_created`, `follow`, `unfollow`,
`account_suspended` (user); `impression_sampled` (1 in 20, with `sample_weight`), `like`,
`reply`, `repost`, `content_reported`, `cascade_closed` (cascade); `moderation_decision`
(moderation shard); `graph_epoch_built` (follow_graph source). Hidden truth (a post's or reply's
policy) goes only to `labels/`.

## Overlays

| Overlay | Adds | Key parameters |
|---|---|---|
| `bot_farm` | Campaigns of one operator, 1–3 promoted accounts and a burst of 20–300 bots under one campaign owner that also carries the promoted accounts' cascades. Bots follow each other, the promoted accounts and popular accounts as cover; they repost each promoted post within seconds and add templated replies (same `content_hash`). Promoted posts are mostly spam, so organic viewers report them; some accounts get suspended. Hidden labels: role (operator, target, bot), outcome (active, suspended), `label_available_at`. Interference: graph (next epoch) and moderation capacity | `size`, `bots`, `targets`, `mutual_follow_p`, `amplify_p`, `amplify_delay`, `reply_p`, `templates`, `spam_p` |

A brigading overlay (mass-reporting an ordinary account) is not included: it needs the
victim's existing cascades to run inside the brigade's campaign owner, which v1 can't do for
accounts that are not cohort members.

## Run

```bash
datagen validate examples/social
datagen run      examples/social --profile sample            # 20k users, 21 days, 3 graph epochs
datagen check    examples/social --profile sample            # -> reports/sample-s42/report.html
datagen run      examples/social --profile abuse             # 2M users + bot_farm
datagen run      examples/social --profile full --overlay bot_farm --set bot_farm.size=60
datagen schema   examples/social --format sql --dialect duckdb --with-fks
datagen replay   examples/social/out/sample-s42 --preset peek
datagen replay   examples/social/out/full-s42+bot_farm --types repost,reply,account_suspended \
                 --with-labels --preset kafka_dev
```

`out/`, `reports/` and `logs/` are empty until the first run.

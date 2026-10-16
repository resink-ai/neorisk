# Brief: microblogging social network

A public microblogging network: short posts, a directed follow graph, reposts that carry a post
to the reposter's followers, likes, replies, and user reports reviewed by a moderation team. We
want event data realistic enough to build and benchmark spam, coordinated-inauthentic-behavior
and virality models, including a bot farm that the base population doesn't contain.

## Actors

- **Users.** Sign up, open the app in sessions, follow and unfollow accounts, post. Activity is
  heavy-tailed: most users lurk and open the app a few times a week; a small share open it many
  times a day. Posting is even more concentrated than visiting: a small share of users write
  most original posts. Each user has a latent *activity* (sessions per day), *influence*
  (how prominently feeds rank their posts) and up to three topics of interest.
- **Follow graph.** Directed: "A follows B" means A sees B's posts and reposts. Both degree
  distributions are heavy-tailed: a few accounts have a large share of all followers; following
  counts are capped at 5,000. About a fifth of edges are reciprocated.
- **Posts and cascades.** An original post reaches the author's followers. A follower who sees
  it may like it, reply to it, repost it (which shows it to *their* followers), or report it.
  The tree of reposts that grows from one original post is its *cascade*. Most posts are never
  reposted; very few reach thousands of people.
- **Topics.** About 40 topics with different virality (news and memes spread; personal updates
  don't) and different report propensity (politics and health get more reports).
- **Moderation.** Reports go to a review queue. Reviewers work through it at a limited rate with
  a day/night rhythm. Each reported item gets one decision: no action, a warning label, a
  takedown, or a takedown plus suspension of the author when the author has three upheld
  violations. Suspended accounts can't act any more.

## Flows

1. **Signup.** Collects region, client (iOS, Android, web) and acquisition channel. Onboarding
   suggests accounts; new users follow 3–20 of them (geometric, mean 8).
2. **Session.** Sessions arrive with Pareto gaps scaled by the user's activity. During a session
   a user may write posts (most sessions write none), follow accounts (follow-backs, friends of
   friends, popular accounts, topic picks) and occasionally unfollow one.
3. **Feed exposure.** A post or repost reaches each follower who opens the app within the post's
   life, with a delay that is log-normal (median about 45 minutes, long tail to days). Feed
   ranking favors influential authors and the follower's topics. Each exposure may produce a
   like (most common), a reply, a repost or a report. Not every view is logged: the product logs
   a 1-in-20 sample of impressions with a sampling weight.
4. **Repost.** A repost shows the original post to the reposter's followers. A user reposts a
   given post at most once and is shown it at most once, however many paths reach them.
5. **Report and review.** A report is filed against a post or a reply and reaches the queue
   within about a second. Duplicate reports on queued items add to its report count. Decisions
   take hours (median under a day). A takedown stops the cascade; a suspension stops the account
   and every cascade it started.
6. **Graph updates.** Follows and unfollows are recorded as they happen, but feeds use the graph
   as rebuilt weekly. Suspensions reach feed ranking within an hour.

## Rates we know (to calibrate against)

| Metric | Target | Source |
|---|---|---|
| In-degree (followers) tail exponent | 1.9–2.6 | Kwak et al. 2010, "What is Twitter…", WWW (≈ 2.28) |
| Out-degree (following) tail exponent, below the 5,000 cap | 2.0–3.0 | Kwak et al. 2010; Myers et al. 2014, WWW |
| Reciprocated share of edges | 18–30% | Kwak et al. 2010 (22.1%) |
| Cascades with no repost | 90–97% | Goel, Watts, Goldstein 2012, EC; Goel et al. 2016, Mgmt. Sci. |
| Cascades reaching 100+ reposts | < 0.1% | Goel et al. 2016 |
| Structural virality, cascades with 100+ nodes | median 2–6 | Goel et al. 2016 (broadcast-dominated) |
| DAU / MAU | 0.35–0.50 | product analytics, H1 |
| Original posts per monthly active user | median 1–3 | Pew Research Center 2019 (median user ≈ 2 per month) |
| Share of original posts by top 10% of posters | 75–85% | Pew Research Center 2019 (≈ 80%) |
| Likes per sampled-weighted impression | 1.5–4% | product analytics, H1 |
| Likes per repost | 4–12 | product analytics, H1 |
| Reports per 10,000 impressions | 0.5–3 | trust & safety dashboard |
| Reviewed items actioned (label or takedown) | 15–35% | trust & safety dashboard |
| Report to decision | median < 24 h, p90 < 72 h | trust & safety SLA |

## Things that must never happen

- A repost whose parent is not an earlier node of the same cascade.
- The same user reposting the same post twice.
- A cascade deeper or larger than the declared caps (the simulator's own safety bound).
- An action by a suspended account after the suspension takes effect: immediately for the
  account's own actions, within the next hourly status refresh for feed-driven ones.
- A moderation decision on content that was never reported, or two decisions on one item.
- Follow and unfollow out of order for a pair (unfollowing someone not followed, or following
  twice in a row).
- Any engagement in a cascade after it closed (taken down, author suspended, or gone quiet).

## Abuse to simulate separately (overlays)

- **Bot farm.** Operators create a few promoted accounts and a burst of 20–300 bots each.
  Bots follow each other and the promoted accounts, follow some popular accounts as cover, and
  amplify every promoted post within seconds with reposts and templated replies (the same few
  texts again and again). Promoted posts are mostly spam. Some get reported, taken down, and
  some bots and promoted accounts get suspended; others stay active. We want to see the effect
  on everyone else: bots change the follow graph for the next epoch, and their reports and
  content consume moderation capacity.

## Out of scope

Direct messages, quote posts, hashtags and search, ads, recommendation of non-followed content
(for-you feeds), edits and deletions by authors, appeals, follow-back triggered by an individual
follow event (follow-backs come from the weekly graph), and deduplication of the same person
seeing related posts from different cascades.

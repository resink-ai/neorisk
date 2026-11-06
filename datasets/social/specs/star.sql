-- Star schema (Kimball). Users never change in the log, so the one dimension is static and
-- facts carry the natural keys. star_dim_users plays two roles in every engagement fact: the
-- acting user (user_id: the viewer, liker or reposter) and the author of the cascade's root
-- post (author_id, looked up from the post fact). Posts are not a dimension: simkit has no
-- posts table to check one against, and a post has no attribute beyond its author and time,
-- which star_fact_posts holds. The follow graph is a factless fact, one row per follow edge.
-- One transaction fact per business event; star_fact_cascade_lifecycle is the accumulating
-- snapshot, one row per root post with its cascade's counts, depth and milestone times.
-- post_id is always the cascade's root post; a repost's own id is repost_id.

-- table: star_dim_users
SELECT user_id, tier, created_at FROM users;

-- table: star_fact_follows
SELECT follow_id, follower_id, followee_id, created_at AS followed_at FROM follows;

-- table: star_fact_posts
SELECT post_id, user_id, event_time AS posted_at FROM post_created;

-- table: star_fact_views
-- via_post is the post or repost whose author exposed the viewer (a follow edge).
SELECT v.event_id AS view_id, v.post_id, v.user_id, p.user_id AS author_id, v.via_post,
       v.event_time AS viewed_at
FROM post_viewed v
JOIN post_created p USING (post_id);

-- table: star_fact_likes
SELECT l.event_id AS like_id, l.post_id, l.user_id, p.user_id AS author_id,
       l.event_time AS liked_at
FROM post_liked l
JOIN post_created p USING (post_id);

-- table: star_fact_reposts
-- depth 1 is a repost of the root itself; parent_id is the root or an earlier repost of the
-- same cascade, parent_user its author.
SELECT r.repost_id, r.post_id, r.user_id, p.user_id AS author_id, r.parent_id, r.parent_user,
       r.depth, r.event_time AS reposted_at
FROM post_reposted r
JOIN post_created p USING (post_id);

-- table: star_fact_cascade_lifecycle
-- One row per root post. max_depth is 0 for a cascade nobody reposted. Milestones: the post,
-- its first view, like and repost, and its last event; nulls where nothing happened.
WITH v AS (
    SELECT post_id, CAST(count(*) AS BIGINT) AS views, min(viewed_at) AS first_view_at,
           max(viewed_at) AS last_view_at
    FROM star_fact_views GROUP BY post_id
), l AS (
    SELECT post_id, CAST(count(*) AS BIGINT) AS likes, min(liked_at) AS first_like_at,
           max(liked_at) AS last_like_at
    FROM star_fact_likes GROUP BY post_id
), r AS (
    SELECT post_id, CAST(count(*) AS BIGINT) AS reposts, max(depth) AS max_depth,
           min(reposted_at) AS first_repost_at, max(reposted_at) AS last_repost_at
    FROM star_fact_reposts GROUP BY post_id
)
SELECT p.post_id, p.user_id AS author_id, p.posted_at,
       coalesce(v.views, 0) AS views, coalesce(l.likes, 0) AS likes,
       coalesce(r.reposts, 0) AS reposts, coalesce(r.max_depth, 0) AS max_depth,
       v.first_view_at, l.first_like_at, r.first_repost_at,
       greatest(p.posted_at, v.last_view_at, l.last_like_at, r.last_repost_at)
           AS last_activity_at
FROM star_fact_posts p
LEFT JOIN v USING (post_id)
LEFT JOIN l USING (post_id)
LEFT JOIN r USING (post_id);

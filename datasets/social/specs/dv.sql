-- Data Vault 2.0. Hash keys are md5 of the business key as text; link keys md5 of the parent
-- hash keys (and a dependent child key) joined by '||'; hashdiff is md5 of the attributes
-- joined by '||' with nulls as ''. Insert-only: load_dts is the event time, record_source
-- the log event type. Hubs for users and posts. A post's business key is its id from the
-- pack's one post id sequence: post_id for an original (first seen at post_created) and
-- repost_id for a repost (first seen at post_reposted), so a repost is a post too and can be
-- the parent of later reposts and the post a view came through. Links: the follow edge
-- (follower, followee, with follow_id as dependent child key, since a pair could be
-- followed, dropped and followed again); authorship (post, user) for originals and reposts;
-- the view (root post, viewer, the post it came through) and the like (root post, user),
-- each with the event id as dependent child key; and the repost (the repost's post, its
-- cascade's root, its parent). Satellites: the user's profile (tier) and the repost's
-- depth.

-- table: dv_hub_users
SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk, user_id, created_at AS load_dts,
       'users_created' AS record_source
FROM users;

-- table: dv_hub_posts
WITH p AS (
    SELECT post_id, event_time, event_type FROM post_created
    UNION ALL
    SELECT repost_id, event_time, event_type FROM post_reposted
)
SELECT md5(CAST(post_id AS VARCHAR)) AS post_hk, post_id, event_time AS load_dts,
       event_type AS record_source
FROM p;

-- table: dv_link_follow
WITH k AS (SELECT md5(CAST(follower_id AS VARCHAR)) AS follower_hk,
                  md5(CAST(followee_id AS VARCHAR)) AS followee_hk, follow_id, created_at
           FROM follows)
SELECT md5(follower_hk || '||' || followee_hk || '||' || CAST(follow_id AS VARCHAR))
           AS follow_hk,
       follower_hk, followee_hk, follow_id, created_at AS load_dts,
       'follows_created' AS record_source
FROM k;

-- table: dv_link_post_author
WITH a AS (
    SELECT post_id, user_id, event_time, event_type FROM post_created
    UNION ALL
    SELECT repost_id, user_id, event_time, event_type FROM post_reposted
), k AS (
    SELECT md5(CAST(post_id AS VARCHAR)) AS post_hk, md5(CAST(user_id AS VARCHAR)) AS user_hk,
           event_time, event_type
    FROM a
)
SELECT md5(post_hk || '||' || user_hk) AS post_author_hk, post_hk, user_hk,
       event_time AS load_dts, event_type AS record_source
FROM k;

-- table: dv_link_view
-- post_hk is the cascade's root post, via_post_hk the post or repost that exposed the viewer.
WITH k AS (SELECT md5(CAST(post_id AS VARCHAR)) AS post_hk,
                  md5(CAST(user_id AS VARCHAR)) AS user_hk,
                  md5(CAST(via_post AS VARCHAR)) AS via_post_hk, event_id, event_time
           FROM post_viewed)
SELECT md5(post_hk || '||' || user_hk || '||' || via_post_hk || '||'
           || CAST(event_id AS VARCHAR)) AS view_hk,
       post_hk, user_hk, via_post_hk, event_id AS view_id, event_time AS load_dts,
       'post_viewed' AS record_source
FROM k;

-- table: dv_link_like
WITH k AS (SELECT md5(CAST(post_id AS VARCHAR)) AS post_hk,
                  md5(CAST(user_id AS VARCHAR)) AS user_hk, event_id, event_time
           FROM post_liked)
SELECT md5(post_hk || '||' || user_hk || '||' || CAST(event_id AS VARCHAR)) AS like_hk,
       post_hk, user_hk, event_id AS like_id, event_time AS load_dts,
       'post_liked' AS record_source
FROM k;

-- table: dv_link_repost
-- repost_hk is the repost's own post hub key, root_hk its cascade's root, parent_hk the post
-- it reposted (the root or an earlier repost). Who reposted is the repost's authorship link;
-- the parent's author is the parent's.
WITH k AS (SELECT md5(CAST(repost_id AS VARCHAR)) AS repost_hk,
                  md5(CAST(post_id AS VARCHAR)) AS root_hk,
                  md5(CAST(parent_id AS VARCHAR)) AS parent_hk, event_time
           FROM post_reposted)
SELECT md5(repost_hk || '||' || root_hk || '||' || parent_hk) AS repost_link_hk,
       repost_hk, root_hk, parent_hk, event_time AS load_dts, 'post_reposted' AS record_source
FROM k;

-- table: dv_sat_users_profile
SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk, created_at AS load_dts,
       'users_created' AS record_source, md5(coalesce(tier, '')) AS hashdiff, tier
FROM users;

-- table: dv_sat_repost_details
SELECT md5(md5(CAST(repost_id AS VARCHAR)) || '||' || md5(CAST(post_id AS VARCHAR)) || '||'
           || md5(CAST(parent_id AS VARCHAR))) AS repost_link_hk,
       event_time AS load_dts, 'post_reposted' AS record_source,
       md5(coalesce(CAST(depth AS VARCHAR), '')) AS hashdiff, depth
FROM post_reposted;

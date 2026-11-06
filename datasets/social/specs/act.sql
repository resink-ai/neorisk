-- Activity schema. One stream, act_user_stream: one row per thing a user (the customer) does,
-- in the standard columns. activity_id is the log's event_id, except for followed_user,
-- which comes from a follows row and takes its follow_id: (activity_id, activity) is the
-- stream's key. link is the cascade's root post id as text on every post activity (a post
-- page), null on followed_user. The features are text:
--   followed_user  feature_1 followee_id
--   created_post   (none; the post is the link)
--   viewed_post    feature_1 author_id, feature_2 via_post
--   liked_post     feature_1 author_id
--   reposted_post  feature_1 author_id, feature_2 repost_id, feature_3 depth
-- author_id is the user who created the root post, so engagement a user received is the
-- stream's rows with that user in feature_1; it is the customer of the created_post with
-- the same link, copied onto the row so no question needs a self-join. A repost's parent
-- post and parent user are not kept (three features are all there is). revenue_impact is
-- null: nothing here moves money. activity_occurrence counts the customer's activities of
-- that kind in ts order (ties by activity_id); activity_repeated_at is the ts of the
-- customer's next one, else null. act_user is the customer table.

-- table: act_user
SELECT user_id AS customer, tier, created_at FROM users;

-- table: act_user_stream
WITH a AS (
    SELECT follow_id AS activity_id, created_at AS ts, follower_id AS customer,
           'followed_user' AS activity, CAST(followee_id AS VARCHAR) AS feature_1,
           CAST(NULL AS VARCHAR) AS feature_2, CAST(NULL AS VARCHAR) AS feature_3,
           CAST(NULL AS VARCHAR) AS link
    FROM follows
    UNION ALL
    SELECT event_id, event_time, user_id, 'created_post', NULL, NULL, NULL,
           CAST(post_id AS VARCHAR)
    FROM post_created
    UNION ALL
    SELECT v.event_id, v.event_time, v.user_id, 'viewed_post', CAST(p.user_id AS VARCHAR),
           CAST(v.via_post AS VARCHAR), NULL, CAST(v.post_id AS VARCHAR)
    FROM post_viewed v JOIN post_created p USING (post_id)
    UNION ALL
    SELECT l.event_id, l.event_time, l.user_id, 'liked_post', CAST(p.user_id AS VARCHAR),
           NULL, NULL, CAST(l.post_id AS VARCHAR)
    FROM post_liked l JOIN post_created p USING (post_id)
    UNION ALL
    SELECT r.event_id, r.event_time, r.user_id, 'reposted_post', CAST(p.user_id AS VARCHAR),
           CAST(r.repost_id AS VARCHAR), CAST(r.depth AS VARCHAR), CAST(r.post_id AS VARCHAR)
    FROM post_reposted r JOIN post_created p USING (post_id)
)
SELECT activity_id, ts, customer, activity, feature_1, feature_2, feature_3,
       CAST(NULL AS BIGINT) AS revenue_impact, link,
       row_number() OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_occurrence,
       lead(ts) OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_repeated_at
FROM a;

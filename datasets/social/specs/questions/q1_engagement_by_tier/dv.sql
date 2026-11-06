-- Root posts are the post hub rows first seen at post_created; each root's author is its
-- authorship link, the author's tier the profile satellite. Views, likes and reposts name
-- the root (post_hk, root_hk).
WITH tier AS (
    SELECT h.user_hk, s.tier
    FROM dv_hub_users h JOIN dv_sat_users_profile s USING (user_hk)
), root AS (
    SELECT p.post_hk, a.user_hk
    FROM dv_hub_posts p JOIN dv_link_post_author a USING (post_hk)
    WHERE p.record_source = 'post_created'
), e AS (
    SELECT post_hk, 1 AS posts, 0 AS views, 0 AS likes, 0 AS reposts FROM root
    UNION ALL
    SELECT post_hk, 0, 1, 0, 0 FROM dv_link_view
    UNION ALL
    SELECT post_hk, 0, 0, 1, 0 FROM dv_link_like
    UNION ALL
    SELECT root_hk, 0, 0, 0, 1 FROM dv_link_repost
), by_user AS (
    SELECT r.user_hk, e.posts, e.views, e.likes, e.reposts
    FROM e JOIN root r USING (post_hk)
)
SELECT t.tier, CAST(coalesce(sum(b.posts), 0) AS BIGINT) AS posts,
       CAST(coalesce(sum(b.views), 0) AS BIGINT) AS views,
       CAST(coalesce(sum(b.likes), 0) AS BIGINT) AS likes,
       CAST(coalesce(sum(b.reposts), 0) AS BIGINT) AS reposts
FROM tier t
LEFT JOIN by_user b USING (user_hk)
GROUP BY t.tier;

-- A post's author is the customer of its created_post; the author of an engaged post is
-- feature_1 of the viewed_post, liked_post and reposted_post rows.
WITH e AS (
    SELECT customer AS author_id, 1 AS posts, 0 AS views, 0 AS likes, 0 AS reposts
    FROM act_user_stream WHERE activity = 'created_post'
    UNION ALL
    SELECT CAST(feature_1 AS BIGINT), 0,
           CASE WHEN activity = 'viewed_post' THEN 1 ELSE 0 END,
           CASE WHEN activity = 'liked_post' THEN 1 ELSE 0 END,
           CASE WHEN activity = 'reposted_post' THEN 1 ELSE 0 END
    FROM act_user_stream
    WHERE activity IN ('viewed_post', 'liked_post', 'reposted_post')
)
SELECT u.tier, CAST(coalesce(sum(e.posts), 0) AS BIGINT) AS posts,
       CAST(coalesce(sum(e.views), 0) AS BIGINT) AS views,
       CAST(coalesce(sum(e.likes), 0) AS BIGINT) AS likes,
       CAST(coalesce(sum(e.reposts), 0) AS BIGINT) AS reposts
FROM act_user u
LEFT JOIN e ON e.author_id = u.customer
GROUP BY u.tier;

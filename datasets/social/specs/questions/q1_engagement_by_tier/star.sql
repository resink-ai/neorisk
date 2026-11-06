-- The engagement facts carry the root post's author (author_id), a second role of the user
-- dimension.
WITH e AS (
    SELECT user_id AS author_id, 1 AS posts, 0 AS views, 0 AS likes, 0 AS reposts
    FROM star_fact_posts
    UNION ALL
    SELECT author_id, 0, 1, 0, 0 FROM star_fact_views
    UNION ALL
    SELECT author_id, 0, 0, 1, 0 FROM star_fact_likes
    UNION ALL
    SELECT author_id, 0, 0, 0, 1 FROM star_fact_reposts
)
SELECT d.tier, CAST(coalesce(sum(e.posts), 0) AS BIGINT) AS posts,
       CAST(coalesce(sum(e.views), 0) AS BIGINT) AS views,
       CAST(coalesce(sum(e.likes), 0) AS BIGINT) AS likes,
       CAST(coalesce(sum(e.reposts), 0) AS BIGINT) AS reposts
FROM star_dim_users d
LEFT JOIN e ON e.author_id = d.user_id
GROUP BY d.tier;

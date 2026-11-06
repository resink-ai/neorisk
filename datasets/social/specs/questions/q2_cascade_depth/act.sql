-- Roots are the created_post activities; a reposted_post's link is its root and feature_3
-- its depth.
WITH r AS (
    SELECT link, max(CAST(feature_3 AS INTEGER)) AS depth
    FROM act_user_stream WHERE activity = 'reposted_post' GROUP BY link
), d AS (
    SELECT CAST(coalesce(r.depth, 0) AS INTEGER) AS max_depth
    FROM act_user_stream p LEFT JOIN r USING (link)
    WHERE p.activity = 'created_post'
)
SELECT max_depth, CAST(count(*) AS BIGINT) AS root_posts FROM d GROUP BY max_depth;

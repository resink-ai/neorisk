-- Root posts by the maximum repost depth of their cascade: 0 when nobody reposted it, 1 when
-- only the root was reposted, n when the deepest repost chain from the root has n reposts.
WITH d AS (
    SELECT p.post_id, CAST(coalesce(max(r.depth), 0) AS INTEGER) AS max_depth
    FROM sim.post_created p LEFT JOIN sim.post_reposted r USING (post_id)
    GROUP BY p.post_id
)
SELECT max_depth, CAST(count(*) AS BIGINT) AS root_posts FROM d GROUP BY max_depth;

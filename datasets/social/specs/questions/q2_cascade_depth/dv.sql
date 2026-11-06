-- Roots are post hub rows first seen at post_created; each repost link names its root, and
-- its depth is on the repost's details satellite.
WITH d AS (
    SELECT p.post_hk, CAST(coalesce(max(s.depth), 0) AS INTEGER) AS max_depth
    FROM dv_hub_posts p
    LEFT JOIN dv_link_repost r ON r.root_hk = p.post_hk
    LEFT JOIN dv_sat_repost_details s USING (repost_link_hk)
    WHERE p.record_source = 'post_created'
    GROUP BY p.post_hk
)
SELECT max_depth, CAST(count(*) AS BIGINT) AS root_posts FROM d GROUP BY max_depth;

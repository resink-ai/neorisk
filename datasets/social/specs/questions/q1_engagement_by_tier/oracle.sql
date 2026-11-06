-- Per author tier: the root posts its users created, and the views, likes and reposts those
-- posts' cascades received (a cascade's engagement is credited to its root post's author,
-- whoever's repost exposed the viewer). Every tier is in the answer, at 0 if it posted
-- nothing.
WITH a AS (
    SELECT p.post_id, u.tier FROM sim.post_created p JOIN sim.users u USING (user_id)
), e AS (
    SELECT a.tier, CAST(count(*) AS BIGINT) AS posts, CAST(0 AS BIGINT) AS views,
           CAST(0 AS BIGINT) AS likes, CAST(0 AS BIGINT) AS reposts
    FROM a GROUP BY a.tier
    UNION ALL
    SELECT a.tier, 0, CAST(count(*) AS BIGINT), 0, 0
    FROM sim.post_viewed v JOIN a USING (post_id) GROUP BY a.tier
    UNION ALL
    SELECT a.tier, 0, 0, CAST(count(*) AS BIGINT), 0
    FROM sim.post_liked l JOIN a USING (post_id) GROUP BY a.tier
    UNION ALL
    SELECT a.tier, 0, 0, 0, CAST(count(*) AS BIGINT)
    FROM sim.post_reposted r JOIN a USING (post_id) GROUP BY a.tier
)
SELECT t.tier, CAST(coalesce(sum(e.posts), 0) AS BIGINT) AS posts,
       CAST(coalesce(sum(e.views), 0) AS BIGINT) AS views,
       CAST(coalesce(sum(e.likes), 0) AS BIGINT) AS likes,
       CAST(coalesce(sum(e.reposts), 0) AS BIGINT) AS reposts
FROM (SELECT DISTINCT tier FROM sim.users) t
LEFT JOIN e USING (tier)
GROUP BY t.tier;

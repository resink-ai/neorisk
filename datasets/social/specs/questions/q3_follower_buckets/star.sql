WITH f AS (
    SELECT followee_id AS user_id, count(*) AS followers
    FROM star_fact_follows GROUP BY followee_id
), b AS (
    SELECT d.tier, coalesce(f.followers, 0) AS n
    FROM star_dim_users d LEFT JOIN f USING (user_id)
), g AS (    -- every bucket for every tier, so an empty bucket is a row with 0 users
    SELECT k.follower_bucket, k.lo, k.hi, t.tier
    FROM (VALUES ('0', 0, 0), ('1-9', 1, 9), ('10-99', 10, 99), ('100+', 100, NULL))
         AS k(follower_bucket, lo, hi)
    CROSS JOIN (SELECT DISTINCT tier FROM star_dim_users) t
)
SELECT g.follower_bucket, g.tier, CAST(count(b.n) AS BIGINT) AS users
FROM g
LEFT JOIN b ON b.tier = g.tier AND b.n >= g.lo AND (g.hi IS NULL OR b.n <= g.hi)
GROUP BY g.follower_bucket, g.tier;

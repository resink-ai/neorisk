-- A user's followers are the follow links with that user's hub key as followee.
WITH f AS (
    SELECT followee_hk AS user_hk, count(*) AS followers
    FROM dv_link_follow GROUP BY followee_hk
), b AS (
    SELECT s.tier, coalesce(f.followers, 0) AS n
    FROM dv_hub_users h
    JOIN dv_sat_users_profile s USING (user_hk)
    LEFT JOIN f USING (user_hk)
), g AS (    -- every bucket for every tier, so an empty bucket is a row with 0 users
    SELECT k.follower_bucket, k.lo, k.hi, t.tier
    FROM (VALUES ('0', 0, 0), ('1-9', 1, 9), ('10-99', 10, 99), ('100+', 100, NULL))
         AS k(follower_bucket, lo, hi)
    CROSS JOIN (SELECT DISTINCT tier FROM dv_sat_users_profile) t
)
SELECT g.follower_bucket, g.tier, CAST(count(b.n) AS BIGINT) AS users
FROM g
LEFT JOIN b ON b.tier = g.tier AND b.n >= g.lo AND (g.hi IS NULL OR b.n <= g.hi)
GROUP BY g.follower_bucket, g.tier;

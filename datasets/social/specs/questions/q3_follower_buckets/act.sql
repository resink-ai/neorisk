-- A user's followers are the followed_user activities with that user in feature_1 (the
-- followee); every user, followed or not, is in act_user.
WITH f AS (
    SELECT CAST(feature_1 AS BIGINT) AS customer, count(*) AS followers
    FROM act_user_stream WHERE activity = 'followed_user' GROUP BY feature_1
), b AS (
    SELECT u.tier, coalesce(f.followers, 0) AS n FROM act_user u LEFT JOIN f USING (customer)
), g AS (    -- every bucket for every tier, so an empty bucket is a row with 0 users
    SELECT k.follower_bucket, k.lo, k.hi, t.tier
    FROM (VALUES ('0', 0, 0), ('1-9', 1, 9), ('10-99', 10, 99), ('100+', 100, NULL))
         AS k(follower_bucket, lo, hi)
    CROSS JOIN (SELECT DISTINCT tier FROM act_user) t
)
SELECT g.follower_bucket, g.tier, CAST(count(b.n) AS BIGINT) AS users
FROM g
LEFT JOIN b ON b.tier = g.tier AND b.n >= g.lo AND (g.hi IS NULL OR b.n <= g.hi)
GROUP BY g.follower_bucket, g.tier;

SELECT CAST(max_depth AS INTEGER) AS max_depth, CAST(count(*) AS BIGINT) AS root_posts
FROM star_fact_cascade_lifecycle
GROUP BY max_depth;

-- local284: the mean item loss rate, and the items below, within and above one SD of it.
-- Written from the question (no gold SQL); matches gold CSV _b, with the population SD
-- (_a is the same without the SD column).
WITH s AS (SELECT avg("loss_rate_%") AS mu FROM veg_loss_rate_df),
 d AS (SELECT mu, sqrt((SELECT avg(("loss_rate_%" - mu) * ("loss_rate_%" - mu))
                        FROM veg_loss_rate_df)) AS sd FROM s)
SELECT sum(l."loss_rate_%" < d.mu - d.sd) AS below_count,
       sum(l."loss_rate_%" BETWEEN d.mu - d.sd AND d.mu + d.sd) AS within_count,
       sum(l."loss_rate_%" > d.mu + d.sd) AS above_count,
       d.mu AS avg_loss, d.sd AS stdev_loss
FROM veg_loss_rate_df l, d;

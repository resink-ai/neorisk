-- name: local077
with a as (select m.month_year, m._year * 100 + m._month ym, p.interest_name, m.composition / m.index_value avg_comp,
                  rank() over (partition by m.month_year order by m.composition / m.index_value desc) rk
           from interest_metrics m join interest_map p on p.id = m.interest_id
           where m.month_year is not null and m._year * 100 + m._month between 201809 and 201908),
t as (select month_year, ym, interest_name, avg_comp from a where rk = 1)
select month_year, interest_name, avg_comp max_index_composition,
       avg(avg_comp) over (order by ym rows between 2 preceding and current row) rolling_avg_3m,
       lag(interest_name) over (order by ym) prev1_name, lag(avg_comp) over (order by ym) prev1_max,
       lag(interest_name, 2) over (order by ym) prev2_name, lag(avg_comp, 2) over (order by ym) prev2_max
from t order by ym;
-- name: local077_ties
select month_year, count(*) top_rows from (select month_year, composition / index_value v, max(composition / index_value) over (partition by month_year) mx
  from interest_metrics where month_year is not null) where v = mx group by 1 having count(*) > 1;
-- name: local078_gold_sql
WITH get_interest_rank AS (
    SELECT t1.month_year, t2.interest_name, t1.composition,
        RANK() OVER (PARTITION BY t2.interest_name ORDER BY t1.composition DESC) AS interest_rank
    FROM interest_metrics AS t1 JOIN interest_map AS t2 ON t1.interest_id = t2.id
    WHERE t1.month_year IS NOT NULL),
get_top_10 AS (SELECT month_year, interest_name, composition FROM get_interest_rank WHERE interest_rank = 1 ORDER BY composition DESC LIMIT 10),
get_bottom_10 AS (SELECT month_year, interest_name, composition FROM get_interest_rank WHERE interest_rank = 1 ORDER BY composition ASC LIMIT 10)
SELECT * FROM get_top_10 UNION SELECT * FROM get_bottom_10 ORDER BY composition DESC;
-- name: local078_pizza_lovers_join
-- the gold partitions by interest_name; 'Pizza Lovers' is two ids
select m.interest_id, m.month_year, m.composition from interest_metrics m join interest_map p on p.id = m.interest_id where p.interest_name = 'Pizza Lovers' order by composition desc limit 5;

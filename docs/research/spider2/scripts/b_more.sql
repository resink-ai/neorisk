.mode list
.headers on
-- short timestamp text examples
select event_time from shopping_cart_events where length(event_time)<=22 limit 4;
-- conversion by visit entry page and impression/click (multi-event visits)
with v as (select visit_id, count(*) n, max(case when sequence_number=1 then page_id end) fp, max(event_type=4) imp, max(event_type=5) clk, max(event_type=3) p, sum(event_type=2) carts, sum(event_type=1 and page_id between 3 and 11) pv from shopping_cart_events group by 1)
select fp, n>1 multi, imp, clk, count(*) visits, round(avg(p),4) conv, round(avg(carts),3) carts, round(avg(pv),3) prodviews from v group by 1,2,3,4;
-- are the 2 visits of a cookie: which comes first in time
with v as (select cookie_id, visit_id, min(event_time) t, max(case when sequence_number=1 then page_id end) fp from shopping_cart_events group by 1,2)
select a.fp first_fp, count(*) from v a join v b on a.cookie_id=b.cookie_id and a.t<b.t group by 1;
-- purchase in both visits of a cookie?
with v as (select cookie_id, visit_id, max(event_type=3) p from shopping_cart_events group by 1,2)
select sum(p) np, count(*) from v group by cookie_id having 1 limit 0;
with v as (select cookie_id, sum(p) np from (select cookie_id, visit_id, max(event_type=3) p from shopping_cart_events group by 1,2) group by 1) select np, count(*) from v group by 1;
-- cookies of a user on distinct dates?
select count(*) users, sum(nd=nc) all_distinct_dates from (select user_id, count(*) nc, count(distinct start_date) nd from shopping_cart_users group by 1);
-- user start_date span per user (days between first and last cookie)
select min(s), avg(s), max(s) from (select julianday(max(start_date))-julianday(min(start_date)) s from shopping_cart_users group by user_id);
-- users rowid order
select group_concat(user_id||':'||start_date, ' ') from (select * from shopping_cart_users order by rowid limit 8);
-- cookie_id = md5(user_id)? first 6 hex of md5 of '1' is c4ca42
select cookie_id from shopping_cart_users where user_id=1 order by rowid;
-- visit_id length / hex
select length(visit_id), count(*) from (select distinct visit_id from shopping_cart_events) group by 1;
-- event rowid order: visits order relative to cookies

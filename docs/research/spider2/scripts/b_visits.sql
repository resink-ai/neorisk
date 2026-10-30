.mode list
-- visit shape by first page
select fp, n, count(*) from (select visit_id, (select page_id from shopping_cart_events e2 where e2.visit_id=e.visit_id and sequence_number=1) fp, count(*) n from shopping_cart_events e group by 1) group by 1,2 order by 1,2 limit 40;
-- per cookie: first-page pattern of its 2 visits
select pat, count(*) from (select cookie_id, group_concat(fp,',') pat from (select cookie_id, visit_id, min(event_time) t, (select page_id from shopping_cart_events e2 where e2.visit_id=e.visit_id and sequence_number=1) fp from shopping_cart_events e group by 1,2 order by 1,3) group by 1) group by 1;
-- time between the two visits of a cookie (seconds)
select min(d), avg(d), max(d) from (select cookie_id, (julianday(max(t))-julianday(min(t)))*86400 d from (select cookie_id, visit_id, min(event_time) t from shopping_cart_events group by 1,2) group by 1);
-- sample cookie
select * from shopping_cart_events where cookie_id='c4ca42' order by event_time;

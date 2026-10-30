-- name: local028 delivered orders by delivered_customer month (2016-10..12 and 2018-08..10)
select substr(order_delivered_customer_date,1,7) m, count(*) from olist_orders where order_status='delivered' and substr(order_delivered_customer_date,1,7) in ('2016-10','2016-11','2016-12','2017-01','2018-08','2018-09','2018-10') group by m order by m
-- name: local028 alt: by purchase month
select substr(order_purchase_timestamp,1,7) m, count(*) from olist_orders where order_status='delivered' and substr(order_purchase_timestamp,1,7) in ('2016-10','2016-12','2017-01','2018-08','2018-09') group by m order by m
-- name: local037 top category x payment type counts
select p.product_category_name, pay.payment_type, count(*) c from olist_order_items i join olist_products p using(product_id) join olist_order_payments pay using(order_id) group by 1,2 order by c desc limit 3
-- name: local032 seller most distinct unique customers (delivered)
select i.seller_id, count(distinct c.customer_unique_id) n, count(distinct i.order_id) o from olist_order_items i join olist_orders o using(order_id) join olist_customers c using(customer_id) where o.order_status='delivered' group by 1 order by 2 desc limit 1
-- name: local032 most 5-star ratings (delivered, item-level join)
select i.seller_id, count(*) from olist_order_items i join olist_orders o using(order_id) join olist_order_reviews r using(order_id) where o.order_status='delivered' and r.review_score=5 group by 1 order by 2 desc limit 1
-- name: local029 top unique customer delivered orders
select c.customer_unique_id, count(distinct o.order_id), avg(p.payment_value) from olist_customers c join olist_orders o using(customer_id) join olist_order_payments p using(order_id) where order_status='delivered' group by 1 order by 2 desc limit 3
-- name: local004 top AOV
select customer_unique_id, count(distinct o.order_id), round(sum(payment_value)/count(distinct o.order_id),2) aov from olist_customers c join olist_orders o using(customer_id) join olist_order_payments using(order_id) group by 1 order by aov desc limit 3
-- name: local037 grain probe: distinct (order,payment_seq) per category x type
select p.product_category_name, pay.payment_type, count(*) rows_, count(distinct pay.order_id||'#'||pay.payment_sequential) dpay, count(distinct pay.order_id) dord from olist_order_items i join olist_products p using(product_id) join olist_order_payments pay using(order_id) where p.product_category_name in ('cama_mesa_banho','beleza_saude') and payment_type='credit_card' group by 1,2
-- name: local032 grain probe: distinct 5-star orders per seller (delivered)
select i.seller_id, count(distinct r.order_id) d_ord, count(distinct r.review_id) d_rev from olist_order_items i join olist_orders o using(order_id) join olist_order_reviews r using(order_id) where o.order_status='delivered' and r.review_score=5 group by 1 order by 2 desc limit 2

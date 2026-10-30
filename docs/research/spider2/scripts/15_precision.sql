-- values with more than 2 decimals (cents-representable check)
select sum(abs(order_amount*100-round(order_amount*100))>1e-6), sum(abs(order_delivery_fee*100-round(order_delivery_fee*100))>1e-6), sum(abs(order_delivery_cost*100-round(order_delivery_cost*100))>1e-6) from orders;
select sum(abs(payment_amount*100-round(payment_amount*100))>1e-6), sum(abs(payment_fee*100-round(payment_fee*100))>1e-6), sum(payment_amount<0), sum(payment_amount=0) from payments;
-- hub/store coordinate decimals sample, store name whitespace
select sum(store_name<>trim(store_name)), sum(length(store_name)) from stores;
-- driver ids range; channels ids range
select min(driver_id), max(driver_id), (select min(channel_id) from channels), (select max(channel_id) from channels), (select min(store_id) from stores), (select max(store_id) from stores), (select min(hub_id) from hubs), (select max(hub_id) from hubs) from drivers

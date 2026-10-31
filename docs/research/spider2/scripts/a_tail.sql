-- node rows starting after last txn date (2020-04-28); and customers whose last txn is before their open-row start
select count(*), sum(end_date like '9999%') from customer_nodes where start_date > '2020-04-28';
select count(*) from (select customer_id, min(start_date) s from customer_nodes where end_date like '9999%' group by 1) o join (select customer_id, max(txn_date) l from customer_transactions group by 1) t using(customer_id) where t.l < o.s;
select count(*) from customer_nodes n1 join customer_nodes n2 on n1.customer_id=n2.customer_id and n1.rowid<n2.rowid and n1.start_date<=n2.end_date and n2.start_date<=n1.end_date;

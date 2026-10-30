-- first 500 rowids: all deposits? distinct customers? each one the customer's first date?
select count(*), count(distinct customer_id), sum(txn_type='deposit') from customer_transactions where rowid<=500;
select count(*) from customer_transactions t where rowid<=500 and txn_date<>(select min(txn_date) from customer_transactions where customer_id=t.customer_id);
-- rows after 500: descents by customer_id, by date within customer
with r as (select rowid id, customer_id c, txn_date d from customer_transactions where rowid>500)
select sum(b.c<a.c), sum(b.c=a.c and b.d<a.d), sum(b.c=a.c and b.d=a.d) from r a join r b on b.id=a.id+1;
-- every customer has a deposit on its first txn day
select count(*) from (select customer_id, min(txn_date) d from customer_transactions group by 1) f where not exists (select 1 from customer_transactions t where t.customer_id=f.customer_id and t.txn_date=f.d and t.txn_type='deposit');
-- rows 501..: block structure? first rows
select rowid, customer_id, txn_date, txn_type from customer_transactions where rowid between 499 and 510;

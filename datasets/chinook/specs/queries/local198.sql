-- local198: median of total sales per country, over countries with more than 4 customers.
-- Written from the question (no gold SQL); 249.53 as in the gold CSV.
with c as (select Country, count(*) n from customers group by 1 having count(*) > 4),
s as (select i.BillingCountry Country, sum(i.Total) tot from invoices i join c on c.Country = i.BillingCountry group by 1),
r as (select tot, row_number() over (order by tot) k, count(*) over () m from s)
select avg(tot) median_total_sales, group_concat(round(tot,2)) totals from r where k in ((m+1)/2, (m+2)/2);

-- Prove legislation_date_dim is a generated calendar: every day 1917-01-01..1999-12-31, once,
-- month_name and day_of_month pure functions of date, rowid = date order.

-- name: span
select min(date) lo, max(date) hi, count(*) n,
  cast(julianday(max(date)) - julianday(min(date)) as int) + 1 days_in_span from legislation_date_dim;

-- name: generated_vs_source
-- rebuild by recursive CTE and compare both ways (EXCEPT on all three columns)
with recursive g(d) as (select '1917-01-01' union all select date(d, '+1 day') from g where d < '1999-12-31'),
gen as (select d date,
  case cast(strftime('%m', d) as int) when 1 then 'January' when 2 then 'February' when 3 then 'March'
    when 4 then 'April' when 5 then 'May' when 6 then 'June' when 7 then 'July' when 8 then 'August'
    when 9 then 'September' when 10 then 'October' when 11 then 'November' else 'December' end month_name,
  cast(strftime('%d', d) as int) day_of_month from g)
select (select count(*) from gen) gen_rows,
  (select count(*) from (select * from gen except select date, month_name, day_of_month from legislation_date_dim)) gen_minus_src,
  (select count(*) from (select date, month_name, day_of_month from legislation_date_dim except select * from gen)) src_minus_gen;

-- name: rowid_is_date_order
select sum(rowid = cast(julianday(date) - julianday('1917-01-01') as int) + 1) aligned, count(*) n from legislation_date_dim;

-- name: types
select typeof(date), typeof(month_name), typeof(day_of_month), count(*) from legislation_date_dim group by 1,2,3;

-- name: used_by_questions_dec31
select count(*) dec31_rows from legislation_date_dim where month_name='December' and day_of_month=31;

-- name: range_vs_terms
-- the calendar is far narrower than the terms (1789..2025): it matches local169's cohort window
select (select min(term_start) from legislators_terms) first_start, (select max(term_end) from legislators_terms) last_end,
  (select count(*) from legislators_terms where term_end < '1917-01-01') terms_ending_before_dim,
  (select count(*) from legislators_terms where term_start > '1999-12-31') terms_starting_after_dim;

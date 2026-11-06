SELECT a.customer AS account_id, a.kind,
       CAST(coalesce(sum(s.revenue_impact), 0) AS BIGINT) AS balance
FROM act_account a LEFT JOIN act_account_stream s USING (customer)
GROUP BY a.customer, a.kind;

SELECT d.acquisition, CAST(count(*) AS BIGINT) AS bonuses, CAST(sum(f.amount) AS BIGINT) AS amount
FROM star_fact_referral_bonus f JOIN star_dim_users d ON d.users_sk = f.inviter_sk
WHERE f.outcome = 'paid'
GROUP BY d.acquisition;

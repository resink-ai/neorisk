SELECT p.acquisition, CAST(count(*) AS BIGINT) AS bonuses, CAST(sum(o.amount) AS BIGINT) AS amount
FROM dv_link_referral_bonus l
JOIN dv_sat_referral_bonus_outcome o USING (referral_bonus_hk)
JOIN dv_sat_users_profile p ON p.user_hk = l.inviter_hk
WHERE o.outcome = 'paid'
GROUP BY p.acquisition;

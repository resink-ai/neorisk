SELECT a.acquisition, CAST(count(*) AS BIGINT) AS bonuses, CAST(sum(m.amount) AS BIGINT) AS amount
FROM an_referral_bonus b
JOIN an_referral_bonus_outcome o USING (bonus_id)
JOIN an_referral_bonus_amount m USING (bonus_id)
JOIN an_referral_bonus_to_users t USING (bonus_id)
JOIN an_users_acquisition a ON a.user_id = t.inviter_id
WHERE o.outcome = 'paid'
GROUP BY a.acquisition;

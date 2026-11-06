-- Referral bonuses paid (count, amount) by the inviter's acquisition channel.
SELECT u.acquisition, CAST(count(*) AS BIGINT) AS bonuses, CAST(sum(b.amount) AS BIGINT) AS amount
FROM sim.referral_bonus_paid b JOIN sim.users u USING (user_id)
GROUP BY u.acquisition;

-- local329: sessions that visit /regist/input and then /regist/confirm (same stamp: later row).
-- Written from the question (no gold SQL); 1, as in the gold CSV.
SELECT count(DISTINCT i.session) n FROM form_log i JOIN form_log c ON c.session=i.session
WHERE i.path='/regist/input' AND c.path='/regist/confirm' AND (c.stamp > i.stamp OR (c.stamp = i.stamp AND c.rowid > i.rowid));

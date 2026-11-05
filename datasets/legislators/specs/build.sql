-- Legislators: events → source tables (refdata rebuild, DuckDB). Dates are YYYY-MM-DD; the
-- REAL columns come back from their integers.

-- table: legislators
SELECT s.full_name, l.first_name, s.last_name, l.middle_name, l.nickname, l.suffix,
       s.other_names_end, CAST(NULL AS DOUBLE) AS other_names_middle, s.other_names_last,
       l.birthday, l.gender, l.ext_id AS id_bioguide, l.id_bioguide_previous_0, l.id_govtrack,
       CAST(l.id_icpsr AS DOUBLE) AS id_icpsr, s.id_wikipedia, l.id_wikidata,
       l.id_google_entity_id, CAST(l.id_house_history AS DOUBLE) AS id_house_history,
       CAST(l.id_house_history_alternate AS DOUBLE) AS id_house_history_alternate,
       CAST(s.id_thomas AS DOUBLE) AS id_thomas, CAST(s.id_cspan AS DOUBLE) AS id_cspan,
       CAST(s.id_votesmart AS DOUBLE) AS id_votesmart, s.id_lis, s.id_ballotpedia,
       s.id_opensecrets, s.id_fec_0, s.id_fec_1, s.id_fec_2
FROM legislators l LEFT JOIN legislators_snapshot s USING (legislator_id);

-- table: legislators_terms
-- term_end is the end event, else the scheduled end of a term open at N.
SELECT l.ext_id AS id_bioguide, s.term_number, l.ext_id || '-' || s.term_number AS term_id,
       s.term_type, strftime(s.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS term_start,
       strftime(coalesce(e.event_time, s.scheduled_end) AT TIME ZONE 'UTC', '%Y-%m-%d')
           AS term_end,
       s.state, CAST(s.district AS DOUBLE) AS district, CAST(s."class" AS DOUBLE) AS "class",
       s.party, s.how, s.url, s.address, s.phone, s.fax, s.contact_form, s.office,
       s.state_rank, s.rss_url, s.caucus
FROM term_started s JOIN legislators l USING (legislator_id)
LEFT JOIN term_ended e ON e.legislator_id = s.legislator_id AND e.term_number = s.term_number;

-- table: legislation_date_dim
-- A generated calendar: every day of 1917-1999, with its English month name.
SELECT strftime(d, '%Y-%m-%d') AS date, strftime(d, '%B') AS month_name,
       CAST(dayofmonth(d) AS BIGINT) AS day_of_month
FROM generate_series(TIMESTAMP '1917-01-01', TIMESTAMP '1999-12-31', INTERVAL 1 DAY) g(d);

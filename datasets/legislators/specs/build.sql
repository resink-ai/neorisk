-- Legislators: events → source tables (refdata rebuild, DuckDB). Dates are YYYY-MM-DD; the
-- REAL columns come back from their integers.

-- table: legislators
SELECT full_name, first_name, last_name, middle_name, nickname, suffix, other_names_end,
       CAST(NULL AS DOUBLE) AS other_names_middle, other_names_last, birthday, gender,
       ext_id AS id_bioguide, id_bioguide_previous_0, id_govtrack,
       CAST(id_icpsr AS DOUBLE) AS id_icpsr, id_wikipedia, id_wikidata, id_google_entity_id,
       CAST(id_house_history AS DOUBLE) AS id_house_history,
       CAST(id_house_history_alternate AS DOUBLE) AS id_house_history_alternate,
       CAST(id_thomas AS DOUBLE) AS id_thomas, CAST(id_cspan AS DOUBLE) AS id_cspan,
       CAST(id_votesmart AS DOUBLE) AS id_votesmart, id_lis, id_ballotpedia, id_opensecrets,
       id_fec_0, id_fec_1, id_fec_2
FROM legislators;

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

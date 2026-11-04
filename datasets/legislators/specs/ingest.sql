-- Legislators: source tables → events (refdata ingest). N = 2020-05-22, the last past term
-- end. legislation_date_dim is a generated calendar and has no block.

-- entity: legislators
-- Created at the first term start (a rule).
SELECT l.id_bioguide AS ext_id, l.full_name, l.first_name, l.last_name, l.middle_name,
       l.nickname, l.suffix, l.other_names_end, l.other_names_last, l.birthday, l.gender,
       l.id_bioguide_previous_0, l.id_govtrack, CAST(l.id_icpsr AS INTEGER) AS id_icpsr,
       l.id_wikipedia, l.id_wikidata, l.id_google_entity_id,
       CAST(l.id_house_history AS INTEGER) AS id_house_history,
       CAST(l.id_house_history_alternate AS INTEGER) AS id_house_history_alternate,
       CAST(l.id_thomas AS INTEGER) AS id_thomas, CAST(l.id_cspan AS INTEGER) AS id_cspan,
       CAST(l.id_votesmart AS INTEGER) AS id_votesmart, l.id_lis, l.id_ballotpedia,
       l.id_opensecrets, l.id_fec_0, l.id_fec_1, l.id_fec_2,
       iso_time(f.first_start, '%Y-%m-%d') AS created_at
FROM legislators l
JOIN (SELECT id_bioguide, min(term_start) AS first_start FROM legislators_terms
      GROUP BY id_bioguide) f USING (id_bioguide)
ORDER BY l.id_bioguide;

-- event: term_started owner=legislator_id ord=k
-- A term still open at N carries its scheduled end.
SELECT iso_time(term_start, '%Y-%m-%d') AS event_time, id_bioguide AS legislator_id,
       term_number, term_type, state, CAST(district AS INTEGER) AS district,
       CAST(class AS INTEGER) AS class, party, how, url, address, phone, fax, contact_form,
       office, state_rank, rss_url, caucus,
       CASE WHEN term_end > '2020-05-22' THEN iso_time(term_end, '%Y-%m-%d') END
           AS scheduled_end,
       2 * term_number AS k
FROM legislators_terms ORDER BY id_bioguide, term_number;

-- event: term_ended owner=legislator_id ord=k
-- Sorts before a next term that starts the same day (2k + 1 < 2k + 2).
SELECT iso_time(term_end, '%Y-%m-%d') AS event_time, id_bioguide AS legislator_id,
       term_number, 2 * term_number + 1 AS k
FROM legislators_terms WHERE term_end <= '2020-05-22' ORDER BY id_bioguide, term_number;

-- name: dob_formats
select case when date_of_birth is null then 'NULL' when date_of_birth glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' then 'YYYY-MM-DD'
 when date_of_birth glob '[0-9][0-9][0-9][0-9]' then 'YYYY' else 'other' end fmt, count(*) n from names group by 1;
-- name: dob_other_samples
select date_of_birth, count(*) from names where date_of_birth is not null and not date_of_birth glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' and not date_of_birth glob '[0-9][0-9][0-9][0-9]' group by 1 limit 20;
-- name: dob_invalid_dates
select count(*) from names where date_of_birth glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' and date(date_of_birth) is not date_of_birth;
-- name: dob_late
select id, name, date_of_birth from names where date_of_birth glob '[0-9][0-9][0-9][0-9]*' and substr(date_of_birth,1,4) >= '2005';
-- name: genre_order_desc
select count(*) pairs, sum(genre < p) desc_alpha from (select genre, lag(genre) over (partition by movie_id order by rowid) p from genre) where p is not null;
-- name: roles_actor_first
select count(*) pairs, sum(not (pc = 'actress' and category = 'actor')) actor_block_first from (select category, lag(category) over (partition by movie_id order by rowid) pc from role_mapping) where pc is not null;
-- name: names_rowid_by_id_runs
-- names table sorted? runs of increasing id
select count(*) runs from (select id, lag(id) over (order by rowid) p from names) where p is null or id < p;
-- name: role_movies_vs_director_movies
select (select count(distinct movie_id) from role_mapping) role_movies, (select count(distinct movie_id) from director_mapping) dir_movies,
 (select count(*) from (select movie_id from role_mapping intersect select movie_id from director_mapping)) both_, (select count(*) from movies where id not in (select movie_id from role_mapping) and id not in (select movie_id from director_mapping)) neither;
-- name: credited_movies_by_year
select m.year, count(*) movies, sum(m.id in (select movie_id from role_mapping)) with_roles, sum(m.id in (select movie_id from director_mapping)) with_dir from movies m group by 1;
-- name: credited_movies_by_votes
select case when r.total_votes < 500 then 'a <500' when r.total_votes < 2000 then 'b 500-1999' when r.total_votes < 10000 then 'c 2k-10k' else 'd 10k+' end band, count(*) n,
 sum(m.id in (select movie_id from role_mapping)) with_roles, sum(m.id in (select movie_id from director_mapping)) with_dir from movies m join ratings r on r.movie_id = m.id group by 1;
-- name: names_credit_coverage
select (select count(*) from names) n, (select count(distinct name_id) from role_mapping) role_people, (select count(distinct name_id) from director_mapping) directors;
-- name: names_unused_with_known_for
select count(*) unused, sum(known_for_movies is not null) with_known_for, sum(known_for_movies in (select id from movies)) known_for_here from names where id not in (select name_id from role_mapping union select name_id from director_mapping);
-- name: name_dups
select count(*) from (select name from names group by 1 having count(*)>1);
-- name: erd_types
select 'ERD.'||c, t, count(*) from (select 'Unnamed: 2' c, typeof("Unnamed: 2") t from ERD union all select 'Unnamed: 6', typeof("Unnamed: 6") from ERD union all select 'Unnamed: 9', typeof("Unnamed: 9") from ERD union all select 'Unnamed: 12', typeof("Unnamed: 12") from ERD) group by 1,2;
-- name: erd_matches_schema
-- ERD (table, column) pairs vs real columns
select e."table", e."column", (select count(*) from pragma_table_info(case e."table" when 'movie' then 'movies' else e."table" end) p where p.name = e."column") exists_ from ERD e;
-- name: erd_real_columns_nonnull
select count("Unnamed: 2") u2, count("Unnamed: 3") u3, count("Unnamed: 4") u4, count("Unnamed: 5") u5, count("Unnamed: 7") u7, count("Unnamed: 8") u8, count("Unnamed: 10") u10, count("Unnamed: 11") u11 from ERD;

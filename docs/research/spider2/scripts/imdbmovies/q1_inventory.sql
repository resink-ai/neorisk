-- name: row_counts
select 'ERD' t, count(*) n from ERD union all select 'movies', count(*) from movies union all select 'genre', count(*) from genre
union all select 'director_mapping', count(*) from director_mapping union all select 'role_mapping', count(*) from role_mapping
union all select 'names', count(*) from names union all select 'ratings', count(*) from ratings;
-- name: sqlite_master
select type, name from sqlite_master order by 1,2;
-- name: typeof_columns
select 'movies.id' c, typeof(id) t, count(*) n from movies group by 2
union all select 'movies.title', typeof(title), count(*) from movies group by 2
union all select 'movies.year', typeof(year), count(*) from movies group by 2
union all select 'movies.date_published', typeof(date_published), count(*) from movies group by 2
union all select 'movies.duration', typeof(duration), count(*) from movies group by 2
union all select 'movies.country', typeof(country), count(*) from movies group by 2
union all select 'movies.worlwide_gross_income', typeof(worlwide_gross_income), count(*) from movies group by 2
union all select 'movies.languages', typeof(languages), count(*) from movies group by 2
union all select 'movies.production_company', typeof(production_company), count(*) from movies group by 2
union all select 'genre.genre', typeof(genre), count(*) from genre group by 2
union all select 'role_mapping.category', typeof(category), count(*) from role_mapping group by 2
union all select 'names.height', typeof(height), count(*) from names group by 2
union all select 'names.date_of_birth', typeof(date_of_birth), count(*) from names group by 2
union all select 'names.known_for_movies', typeof(known_for_movies), count(*) from names group by 2
union all select 'ratings.avg_rating', typeof(avg_rating), count(*) from ratings group by 2
union all select 'ratings.total_votes', typeof(total_votes), count(*) from ratings group by 2
union all select 'ratings.median_rating', typeof(median_rating), count(*) from ratings group by 2;
-- name: empties
select 'movies.country' c, sum(country='') empty, sum(country is null) nul from movies
union all select 'movies.worlwide_gross_income', sum(worlwide_gross_income=''), sum(worlwide_gross_income is null) from movies
union all select 'movies.languages', sum(languages=''), sum(languages is null) from movies
union all select 'movies.production_company', sum(production_company=''), sum(production_company is null) from movies
union all select 'names.date_of_birth', sum(date_of_birth=''), sum(date_of_birth is null) from names
union all select 'names.known_for_movies', sum(known_for_movies=''), sum(known_for_movies is null) from names
union all select 'names.height', sum(height=''), sum(height is null) from names;
-- name: key_uniqueness
select 'movies.id' k, count(*) n, count(distinct id) d from movies
union all select 'names.id', count(*), count(distinct id) from names
union all select 'ratings.movie_id', count(*), count(distinct movie_id) from ratings
union all select 'genre(movie_id,genre)', count(*), count(distinct movie_id||'|'||genre) from genre
union all select 'director_mapping(m,n)', count(*), count(distinct movie_id||'|'||name_id) from director_mapping
union all select 'role_mapping(m,n)', count(*), count(distinct movie_id||'|'||name_id) from role_mapping
union all select 'role_mapping(m,n,c)', count(*), count(distinct movie_id||'|'||name_id||'|'||category) from role_mapping;
-- name: full_row_dups
select 'role_mapping' t, count(*) - (select count(*) from (select distinct * from role_mapping)) extra from role_mapping
union all select 'director_mapping', count(*) - (select count(*) from (select distinct * from director_mapping)) from director_mapping
union all select 'genre', count(*) - (select count(*) from (select distinct * from genre)) from genre
union all select 'names', count(*) - (select count(*) from (select distinct * from names)) from names;
-- name: role_dup_samples
select movie_id, name_id, category, count(*) from role_mapping group by 1,2,3 having count(*)>1 limit 10;
-- name: role_dup_shape
select c copies, count(*) pairs from (select count(*) c from role_mapping group by movie_id, name_id, category having count(*)>1) group by 1;
-- name: role_two_categories
select count(*) from (select movie_id, name_id from role_mapping group by 1,2 having count(distinct category)>1);
-- name: fk_orphans
select 'ratings.movie_id->movies' fk, count(*) n, sum(movie_id not in (select id from movies)) orphans from ratings
union all select 'genre.movie_id->movies', count(*), sum(movie_id not in (select id from movies)) from genre
union all select 'director_mapping.movie_id->movies', count(*), sum(movie_id not in (select id from movies)) from director_mapping
union all select 'director_mapping.name_id->names', count(*), sum(name_id not in (select id from names)) from director_mapping
union all select 'role_mapping.movie_id->movies', count(*), sum(movie_id not in (select id from movies)) from role_mapping
union all select 'role_mapping.name_id->names', count(*), sum(name_id not in (select id from names)) from role_mapping
union all select 'names.known_for_movies->movies', count(known_for_movies), sum(known_for_movies <> '' and known_for_movies not in (select id from movies)) from names;
-- name: coverage
select (select count(*) from movies where id not in (select movie_id from ratings)) no_rating,
 (select count(*) from movies where id not in (select movie_id from genre)) no_genre,
 (select count(*) from movies where id not in (select movie_id from director_mapping)) no_director,
 (select count(*) from movies where id not in (select movie_id from role_mapping)) no_role,
 (select count(*) from names where id not in (select name_id from role_mapping union select name_id from director_mapping)) names_unused,
 (select count(*) from names where id in (select name_id from role_mapping) and id in (select name_id from director_mapping)) role_and_director;
-- name: known_for_shape
select (length(known_for_movies) - length(replace(known_for_movies, ',', ''))) commas, count(*) from names where known_for_movies <> '' group by 1;
-- name: known_for_in_credits
-- is known_for_movies one of the person's credited movies here?
select count(*) nonempty, sum(exists(select 1 from role_mapping r where r.name_id = n.id and r.movie_id = n.known_for_movies) or exists(select 1 from director_mapping d where d.name_id = n.id and d.movie_id = n.known_for_movies)) is_credit
from names n where known_for_movies <> '';
-- name: rowid_orders
select 'movies by id' t, count(*) pairs, sum(id > p) incr from (select id, lag(id) over (order by rowid) p from movies) where p is not null
union all select 'names by id', count(*), sum(id > p) from (select id, lag(id) over (order by rowid) p from names) where p is not null
union all select 'ratings by movie_id', count(*), sum(movie_id > p) from (select movie_id, lag(movie_id) over (order by rowid) p from ratings) where p is not null
union all select 'genre by movie_id', count(*), sum(movie_id >= p) from (select movie_id, lag(movie_id) over (order by rowid) p from genre) where p is not null
union all select 'role by movie_id', count(*), sum(movie_id >= p) from (select movie_id, lag(movie_id) over (order by rowid) p from role_mapping) where p is not null
union all select 'director by movie_id', count(*), sum(movie_id >= p) from (select movie_id, lag(movie_id) over (order by rowid) p from director_mapping) where p is not null;
-- name: movies_rowid_order_by_year
select count(*) pairs, sum(y >= p) nondecr from (select year y, lag(year) over (order by rowid) p from movies) where p is not null;
-- name: ratings_rowid_vs_movies_rowid
select count(*) n, sum(r.rowid = m.rowid) same_row from ratings r join movies m on m.id = r.movie_id;
-- name: erd_rows
select * from ERD;

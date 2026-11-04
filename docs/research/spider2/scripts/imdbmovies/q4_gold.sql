-- name: local152_top9_directors
with d as (select dm.name_id, n.name, m.id, m.date_published dp, m.duration, r.avg_rating, r.total_votes
  from director_mapping dm join names n on n.id = dm.name_id join movies m on m.id = dm.movie_id join ratings r on r.movie_id = m.id),
g as (select name_id, julianday(dp) - julianday(lag(dp) over (partition by name_id order by dp)) gap from d)
select d.name_id, d.name, count(*) movie_count, (select round(avg(gap)) from g where g.name_id = d.name_id) avg_inter,
  round(avg(avg_rating), 2) avg_rating, sum(total_votes) total_votes, min(avg_rating), max(avg_rating), sum(duration) total_duration
from d group by d.name_id order by movie_count desc, total_duration desc limit 9;
-- name: local230_top_genres
select g.genre, count(distinct g.movie_id) n from genre g join ratings r using(movie_id) where r.avg_rating > 8 group by 1 order by 2 desc limit 4;
-- name: local230_top_directors
with tg as (select g.genre from genre g join ratings r using(movie_id) where r.avg_rating > 8 group by 1 order by count(distinct g.movie_id) desc limit 3)
select n.name director, count(distinct dm.movie_id) movie_count
from director_mapping dm join names n on n.id = dm.name_id join ratings r on r.movie_id = dm.movie_id join genre g on g.movie_id = dm.movie_id
where r.avg_rating > 8 and g.genre in (select genre from tg) group by dm.name_id order by 2 desc, 1 limit 6;

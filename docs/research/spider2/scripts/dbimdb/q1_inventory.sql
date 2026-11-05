-- name: row_counts
select 'Movie' t, count(*) n from Movie union all select 'Genre', count(*) from Genre
union all select 'Language', count(*) from Language union all select 'Country', count(*) from Country
union all select 'Location', count(*) from Location union all select 'M_Location', count(*) from M_Location
union all select 'M_Country', count(*) from M_Country union all select 'M_Language', count(*) from M_Language
union all select 'M_Genre', count(*) from M_Genre union all select 'Person', count(*) from Person
union all select 'M_Producer', count(*) from M_Producer union all select 'M_Director', count(*) from M_Director
union all select 'M_Cast', count(*) from M_Cast;
-- name: sqlite_master
select type, name, tbl_name from sqlite_master order by type, name;
-- name: typeof_columns
select 'Movie.index' c, typeof("index") t, count(*) n from Movie group by 2
union all select 'Movie.MID', typeof(MID), count(*) from Movie group by 2
union all select 'Movie.title', typeof(title), count(*) from Movie group by 2
union all select 'Movie.year', typeof(year), count(*) from Movie group by 2
union all select 'Movie.rating', typeof(rating), count(*) from Movie group by 2
union all select 'Movie.num_votes', typeof(num_votes), count(*) from Movie group by 2
union all select 'Genre.Name', typeof(Name), count(*) from Genre group by 2
union all select 'Genre.GID', typeof(GID), count(*) from Genre group by 2
union all select 'Language.LAID', typeof(LAID), count(*) from Language group by 2
union all select 'Country.CID', typeof(CID), count(*) from Country group by 2
union all select 'Location.LID', typeof(LID), count(*) from Location group by 2
union all select 'M_Location.LID', typeof(LID), count(*) from M_Location group by 2
union all select 'M_Country.CID', typeof(CID), count(*) from M_Country group by 2
union all select 'M_Language.LAID', typeof(LAID), count(*) from M_Language group by 2
union all select 'M_Genre.GID', typeof(GID), count(*) from M_Genre group by 2
union all select 'Person.PID', typeof(PID), count(*) from Person group by 2
union all select 'Person.Name', typeof(Name), count(*) from Person group by 2
union all select 'Person.Gender', typeof(Gender), count(*) from Person group by 2
union all select 'M_Producer.PID', typeof(PID), count(*) from M_Producer group by 2
union all select 'M_Director.PID', typeof(PID), count(*) from M_Director group by 2
union all select 'M_Cast.PID', typeof(PID), count(*) from M_Cast group by 2
union all select 'M_Cast.MID', typeof(MID), count(*) from M_Cast group by 2;
-- name: index_is_rowid_minus_1
select 'Movie' t, count(*) n, sum("index" = rowid-1) ok from Movie
union all select 'Genre', count(*), sum("index" = rowid-1) from Genre
union all select 'Language', count(*), sum("index" = rowid-1) from Language
union all select 'Country', count(*), sum("index" = rowid-1) from Country
union all select 'Location', count(*), sum("index" = rowid-1) from Location
union all select 'M_Location', count(*), sum("index" = rowid-1) from M_Location
union all select 'M_Country', count(*), sum("index" = rowid-1) from M_Country
union all select 'M_Language', count(*), sum("index" = rowid-1) from M_Language
union all select 'M_Genre', count(*), sum("index" = rowid-1) from M_Genre
union all select 'Person', count(*), sum("index" = rowid-1) from Person
union all select 'M_Producer', count(*), sum("index" = rowid-1) from M_Producer
union all select 'M_Director', count(*), sum("index" = rowid-1) from M_Director
union all select 'M_Cast', count(*), sum("index" = rowid-1) from M_Cast;
-- name: link_id_equals_index
select 'M_Location' t, count(*) n, sum(ID = "index") ok from M_Location
union all select 'M_Country', count(*), sum(ID = "index") from M_Country
union all select 'M_Language', count(*), sum(ID = "index") from M_Language
union all select 'M_Genre', count(*), sum(ID = "index") from M_Genre
union all select 'M_Producer', count(*), sum(ID = "index") from M_Producer
union all select 'M_Director', count(*), sum(ID = "index") from M_Director
union all select 'M_Cast', count(*), sum(ID = "index") from M_Cast;
-- name: lookup_id_equals_index
select 'Genre' t, count(*) n, sum(GID = "index") ok from Genre
union all select 'Language', count(*), sum(LAID = "index") from Language
union all select 'Country', count(*), sum(CID = "index") from Country
union all select 'Location', count(*), sum(LID = "index") from Location;
-- name: key_uniqueness
select 'Movie.MID' k, count(*) n, count(distinct MID) d, count(distinct trim(MID)) d_trim from Movie
union all select 'Person.PID', count(*), count(distinct PID), count(distinct trim(PID)) from Person
union all select 'Genre.Name', count(*), count(distinct Name), count(distinct trim(Name)) from Genre
union all select 'Language.Name', count(*), count(distinct Name), count(distinct trim(Name)) from Language
union all select 'Country.Name', count(*), count(distinct Name), count(distinct trim(Name)) from Country
union all select 'Location.Name', count(*), count(distinct Name), count(distinct trim(Name)) from Location
union all select 'M_Location.MID', count(*), count(distinct MID), count(distinct trim(MID)) from M_Location
union all select 'M_Country.MID', count(*), count(distinct MID), count(distinct trim(MID)) from M_Country
union all select 'M_Language.MID', count(*), count(distinct MID), count(distinct trim(MID)) from M_Language
union all select 'M_Genre.MID', count(*), count(distinct MID), count(distinct trim(MID)) from M_Genre
union all select 'M_Director.MID', count(*), count(distinct MID), count(distinct trim(MID)) from M_Director
union all select 'M_Producer(MID,PID)', count(*), count(distinct MID||'|'||PID), count(distinct trim(MID)||'|'||trim(PID)) from M_Producer
union all select 'M_Cast(MID,PID)', count(*), count(distinct MID||'|'||PID), count(distinct trim(MID)||'|'||trim(PID)) from M_Cast;
-- name: whitespace_ids
select 'Movie.MID' c, count(*) n, sum(MID <> trim(MID)) padded, sum(substr(MID,1,1)=' ') lead_sp, sum(substr(MID,-1)=' ') trail_sp from Movie
union all select 'Person.PID', count(*), sum(PID<>trim(PID)), sum(substr(PID,1,1)=' '), sum(substr(PID,-1)=' ') from Person
union all select 'Person.Name', count(*), sum(Name<>trim(Name)), sum(substr(Name,1,1)=' '), sum(substr(Name,-1)=' ') from Person
union all select 'Movie.title', count(*), sum(title<>trim(title)), sum(substr(title,1,1)=' '), sum(substr(title,-1)=' ') from Movie
union all select 'Genre.Name', count(*), sum(Name<>trim(Name)), sum(substr(Name,1,1)=' '), sum(substr(Name,-1)=' ') from Genre
union all select 'Language.Name', count(*), sum(Name<>trim(Name)), sum(substr(Name,1,1)=' '), sum(substr(Name,-1)=' ') from Language
union all select 'Country.Name', count(*), sum(Name<>trim(Name)), sum(substr(Name,1,1)=' '), sum(substr(Name,-1)=' ') from Country
union all select 'Location.Name', count(*), sum(Name<>trim(Name)), sum(substr(Name,1,1)=' '), sum(substr(Name,-1)=' ') from Location
union all select 'M_Cast.MID', count(*), sum(MID<>trim(MID)), sum(substr(MID,1,1)=' '), sum(substr(MID,-1)=' ') from M_Cast
union all select 'M_Cast.PID', count(*), sum(PID<>trim(PID)), sum(substr(PID,1,1)=' '), sum(substr(PID,-1)=' ') from M_Cast
union all select 'M_Producer.PID', count(*), sum(PID<>trim(PID)), sum(substr(PID,1,1)=' '), sum(substr(PID,-1)=' ') from M_Producer
union all select 'M_Producer.MID', count(*), sum(MID<>trim(MID)), sum(substr(MID,1,1)=' '), sum(substr(MID,-1)=' ') from M_Producer
union all select 'M_Director.PID', count(*), sum(PID<>trim(PID)), sum(substr(PID,1,1)=' '), sum(substr(PID,-1)=' ') from M_Director
union all select 'M_Director.MID', count(*), sum(MID<>trim(MID)), sum(substr(MID,1,1)=' '), sum(substr(MID,-1)=' ') from M_Director;
-- name: padding_shapes
select 'Person.PID' c, length(PID)-length(ltrim(PID)) lead, length(PID)-length(rtrim(PID)) trail, count(*) n from Person group by 2,3
union all select 'Person.Name', length(Name)-length(ltrim(Name)), length(Name)-length(rtrim(Name)), count(*) from Person group by 2,3
union all select 'Genre.Name', length(Name)-length(ltrim(Name)), length(Name)-length(rtrim(Name)), count(*) from Genre group by 2,3
union all select 'M_Cast.PID', length(PID)-length(ltrim(PID)), length(PID)-length(rtrim(PID)), count(*) from M_Cast group by 2,3
union all select 'M_Producer.PID', length(PID)-length(ltrim(PID)), length(PID)-length(rtrim(PID)), count(*) from M_Producer group by 2,3
union all select 'M_Director.PID', length(PID)-length(ltrim(PID)), length(PID)-length(rtrim(PID)), count(*) from M_Director group by 2,3
union all select 'Movie.title', length(title)-length(ltrim(title)), length(title)-length(rtrim(title)), count(*) from Movie group by 2,3;
-- name: other_whitespace
select 'Person.Name tab/nl/nbsp' c, sum(instr(Name, char(9))>0) tab, sum(instr(Name, char(10))>0) nl, sum(instr(Name, char(160))>0) nbsp, sum(instr(Name,'  ')>0) dbl from Person
union all select 'Movie.title', sum(instr(title, char(9))>0), sum(instr(title, char(10))>0), sum(instr(title, char(160))>0), sum(instr(title,'  ')>0) from Movie;
-- name: nulls_and_empties
select 'Movie' t, sum(MID is null) a, sum(title is null) b, sum(year is null) c, sum(rating is null) d, sum(num_votes is null) e, sum(title='') f, sum(year='') g from Movie
union all select 'Person', sum(PID is null), sum(Name is null), sum(Gender is null), sum(Name=''), sum(Gender=''), sum(trim(Name)=''), sum(Gender='None') from Person
union all select 'M_Location', sum(MID is null), sum(LID is null), sum(ID is null), 0,0,0,0 from M_Location
union all select 'M_Country', sum(MID is null), sum(CID is null), sum(ID is null), 0,0,0,0 from M_Country
union all select 'M_Language', sum(MID is null), sum(LAID is null), 0,0,0,0,0 from M_Language
union all select 'M_Genre', sum(MID is null), sum(GID is null), 0,0,0,0,0 from M_Genre
union all select 'M_Cast', sum(MID is null), sum(PID is null), 0,0,0,0,0 from M_Cast
union all select 'M_Producer', sum(MID is null), sum(PID is null), 0,0,0,0,0 from M_Producer
union all select 'M_Director', sum(MID is null), sum(PID is null), 0,0,0,0,0 from M_Director;
-- name: gender_values
select quote(Gender) g, count(*) n from Person group by 1 order by 2 desc;
-- name: year_shapes
select length(year) len, typeof(year) t, count(*) n, min(year), max(year) from Movie group by 1,2;
-- name: year_nonnumeric_samples
select year, count(*) from Movie where year glob '*[^0-9]*' group by 1 order by 2 desc limit 30;
-- name: year_distinct_prefixes
select substr(year,1,length(year)-4) prefix, count(*) n from Movie group by 1 order by 2 desc;
-- name: lookup_values
select 'Language' t, LAID id, quote(Name) name from Language
union all select 'Country', CID, quote(Name) from Country;
-- name: rating_shapes
select typeof(rating) t, count(*) n, min(rating), max(rating), sum(rating*10 <> cast(rating*10 as integer)) non_tenths from Movie group by 1;
-- name: votes_shapes
select typeof(num_votes), count(*), min(num_votes), max(num_votes) from Movie group by 1;
-- name: real_id_columns
select 'M_Location.LID' c, count(*) n, sum(LID = cast(LID as integer)) whole, sum(LID is null) nulls from M_Location
union all select 'M_Country.CID', count(*), sum(CID = cast(CID as integer)), sum(CID is null) from M_Country;

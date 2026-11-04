-- Is alien_data a pure function of aliens + aliens_details + aliens_location (joined on id = detail_id = loc_id)?

-- name: setup_indexes
create index ia on aliens(id); create index idd on aliens_details(detail_id); create index il on aliens_location(loc_id); create index iad on alien_data(id);

-- name: keys
select (select count(distinct id) from aliens) a, (select count(distinct detail_id) from aliens_details) d,
  (select count(distinct loc_id) from aliens_location) l, (select count(distinct id) from alien_data) ad,
  (select count(*) from aliens a join aliens_details d on d.detail_id = a.id join aliens_location l on l.loc_id = a.id join alien_data x on x.id = a.id) joined_all;

-- name: rowid_is_id
select (select sum(rowid = id) from aliens) a, (select sum(rowid = detail_id) from aliens_details) d,
  (select sum(rowid = loc_id) from aliens_location) l, (select sum(rowid = id) from alien_data) ad;

-- name: per_column_lower_match
select sum(x.first_name is lower(a.first_name)) first_name, sum(x.first_name is null) fn_null,
  sum(x.last_name = lower(a.last_name)) last_name, sum(x.email = a.email) email, sum(x.type = lower(a.type)) type,
  sum(x.birth_year = a.birth_year) birth_year, sum(x.favorite_food = lower(d.favorite_food)) food,
  sum(x.feeding_frequency = lower(d.feeding_frequency)) freq, sum(x.aggressive = d.aggressive) aggressive,
  sum(x.occupation = lower(l.occupation)) occupation, sum(x.current_location = lower(l.current_location)) loc,
  sum(x.state = lower(l.state)) state, sum(x.country = lower(l.country)) country, count(*) n
from alien_data x join aliens a on a.id = x.id join aliens_details d on d.detail_id = x.id join aliens_location l on l.loc_id = x.id;

-- name: null_first_names
select a.id, '['||a.first_name||']' src, x.first_name from aliens a join alien_data x using(id) where x.first_name is null;

-- name: age_rule
select x.age + x.birth_year s, count(*) from alien_data x group by 1;

-- name: gender_map
select a.gender src, x.gender dst, count(*) from aliens a join alien_data x using(id) group by 1,2 order by 1,2;

-- name: region_is_function_of_state
select count(*) states, sum(r = 1) single_region from (select state, count(distinct us_region) r from alien_data group by 1);

-- name: region_map
select us_region, count(distinct state) states, group_concat(distinct state) from alien_data group by 1 order by 1;

-- name: full_rebuild_except
-- rebuild alien_data with lower() ('Nan' -> NULL: pandas reads the name Nan as NaN), the gender map, age = 2024 - birth_year, and the observed state -> region map
with rm as (select distinct state, us_region from alien_data),
gm as (select distinct a.gender src, x.gender dst from aliens a join alien_data x using(id)),
b as (select a.id, case when a.first_name = 'Nan' then null else lower(a.first_name) end first_name, lower(a.last_name) last_name, a.email,
  gm.dst gender, lower(a.type) type, a.birth_year, 2024 - a.birth_year age, lower(d.favorite_food) favorite_food,
  lower(d.feeding_frequency) feeding_frequency, d.aggressive, lower(l.occupation) occupation, lower(l.current_location) current_location,
  lower(l.state) state, rm.us_region, lower(l.country) country
  from aliens a join aliens_details d on d.detail_id = a.id join aliens_location l on l.loc_id = a.id
  join gm on gm.src = a.gender join rm on rm.state = lower(l.state))
select (select count(*) from b) rebuilt,
  (select count(*) from (select * from b except select * from alien_data)) b_minus_src,
  (select count(*) from (select * from alien_data except select * from b)) src_minus_b;

-- name: case_collisions
-- lower() merges distinct source spellings
select 'first_name' c, (select count(distinct first_name) from aliens) src, (select count(distinct lower(first_name)) from aliens) lowered
union all select 'last_name', (select count(distinct last_name) from aliens), (select count(distinct lower(last_name)) from aliens);

-- name: full_rebuild_literal_maps
-- same rebuild, but with literal maps (what build.sql would carry): BEA regions, and gender -> {female, male, non-binary}
with rm(state, us_region) as (values
 ('california','far west'),('washington','far west'),('hawaii','far west'),('oregon','far west'),('alaska','far west'),('nevada','far west'),
 ('ohio','great lakes'),('michigan','great lakes'),('illinois','great lakes'),('wisconsin','great lakes'),('indiana','great lakes'),
 ('maryland','mideast'),('pennsylvania','mideast'),('new jersey','mideast'),('district of columbia','mideast'),('new york','mideast'),('delaware','mideast'),
 ('connecticut','new england'),('rhode island','new england'),('massachusetts','new england'),('maine','new england'),('new hampshire','new england'),('vermont','new england'),
 ('nebraska','plains'),('missouri','plains'),('kansas','plains'),('south dakota','plains'),('minnesota','plains'),('iowa','plains'),('north dakota','plains'),
 ('utah','rocky mountain'),('montana','rocky mountain'),('colorado','rocky mountain'),('idaho','rocky mountain'),('wyoming','rocky mountain'),
 ('virginia','southeast'),('georgia','southeast'),('florida','southeast'),('north carolina','southeast'),('arkansas','southeast'),('kentucky','southeast'),
 ('tennessee','southeast'),('alabama','southeast'),('west virginia','southeast'),('louisiana','southeast'),('south carolina','southeast'),('mississippi','southeast'),
 ('texas','southwest'),('oklahoma','southwest'),('arizona','southwest'),('new mexico','southwest')),
b as (select a.id, case when a.first_name = 'Nan' then null else lower(a.first_name) end first_name, lower(a.last_name) last_name, a.email,
  case a.gender when 'Female' then 'female' when 'Male' then 'male' else 'non-binary' end gender, lower(a.type) type, a.birth_year,
  2024 - a.birth_year age, lower(d.favorite_food) favorite_food, lower(d.feeding_frequency) feeding_frequency, d.aggressive,
  lower(l.occupation) occupation, lower(l.current_location) current_location, lower(l.state) state, rm.us_region, lower(l.country) country
  from aliens a join aliens_details d on d.detail_id = a.id join aliens_location l on l.loc_id = a.id left join rm on rm.state = lower(l.state))
select (select count(*) from b) rebuilt, (select count(*) from b where us_region is null) unmapped,
  (select count(*) from (select * from b except select * from alien_data)) b_minus_src,
  (select count(*) from (select * from alien_data except select * from b)) src_minus_b;

-- name: nan_names_elsewhere
select 'aliens.first_name' c, count(*) from aliens where first_name in ('Nan','NaN','NULL','None','NA','N/A','null')
union all select 'aliens.last_name', count(*) from aliens where last_name in ('Nan','NaN','NULL','None','NA','N/A','null');

-- name: local010_buckets
with c as (select a.airport_code code, json_extract(a.city,'$.en') city,
  cast(substr(coordinates,2,instr(coordinates,',')-2) as real) lon,
  cast(substr(coordinates, instr(coordinates,',')+1, length(coordinates)-instr(coordinates,',')-1) as real) lat from airports_data a),
d as (select case when c1.city<c2.city then c1.city else c2.city end city1, case when c1.city<c2.city then c2.city else c1.city end city2,
  2*6371*asin(sqrt(power(sin((radians(c2.lat)-radians(c1.lat))/2),2)+cos(radians(c1.lat))*cos(radians(c2.lat))*power(sin((radians(c2.lon)-radians(c1.lon))/2),2))) km
  from flights f join c c1 on c1.code=f.departure_airport join c c2 on c2.code=f.arrival_airport),
p as (select city1, city2, avg(km) avgkm from d group by 1,2)
select case when avgkm>=6000 then 6000 else cast(avgkm/1000 as int)*1000 end bucket, count(*) pairs from p group by 1 order by 1;
-- name: local010_flights_per_bucket
with c as (select a.airport_code code, json_extract(a.city,'$.en') city,
  cast(substr(coordinates,2,instr(coordinates,',')-2) as real) lon,
  cast(substr(coordinates, instr(coordinates,',')+1, length(coordinates)-instr(coordinates,',')-1) as real) lat from airports_data a),
d as (select case when c1.city<c2.city then c1.city else c2.city end city1, case when c1.city<c2.city then c2.city else c1.city end city2,
  2*6371*asin(sqrt(power(sin((radians(c2.lat)-radians(c1.lat))/2),2)+cos(radians(c1.lat))*cos(radians(c2.lat))*power(sin((radians(c2.lon)-radians(c1.lon))/2),2))) km
  from flights f join c c1 on c1.code=f.departure_airport join c c2 on c2.code=f.arrival_airport),
p as (select city1, city2, avg(km) avgkm, count(*) n from d group by 1,2)
select case when avgkm>=6000 then 6000 else cast(avgkm/1000 as int)*1000 end bucket, count(*) pairs, sum(n) flights from p group by 1 order by 1;
-- name: local010_route_rows_city_names_ru
select count(distinct departure_airport||arrival_airport) from flights;

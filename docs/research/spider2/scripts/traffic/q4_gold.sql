-- name: local017_gold_sql
WITH AnnualTotals AS (
    SELECT 
        STRFTIME('%Y', collision_date) AS Year, 
        COUNT(case_id) AS AnnualTotal
    FROM 
        collisions
    GROUP BY 
        Year
),
CategoryTotals AS (
    SELECT 
        STRFTIME('%Y', collision_date) AS Year,
        pcf_violation_category AS Category,
        COUNT(case_id) AS Subtotal
    FROM 
        collisions
    GROUP BY 
        Year, Category
),
CategoryPercentages AS (
    SELECT 
        ct.Year,
        ct.Category,
        ROUND((ct.Subtotal * 100.0) / at.AnnualTotal, 1) AS PercentageOfAnnualRoadIncidents
    FROM 
        CategoryTotals ct
    JOIN 
        AnnualTotals at ON ct.Year = at.Year
),
RankedCategories AS (
    SELECT
        Year,
        Category,
        PercentageOfAnnualRoadIncidents,
        ROW_NUMBER() OVER (PARTITION BY Year ORDER BY PercentageOfAnnualRoadIncidents DESC) AS Rank
    FROM
        CategoryPercentages
),
TopTwoCategories AS (
    SELECT
        Year,
        GROUP_CONCAT(Category, ', ') AS TopCategories
    FROM
        RankedCategories
    WHERE
        Rank <= 2
    GROUP BY
        Year
),
UniqueYear AS (
    SELECT
        Year
    FROM
        TopTwoCategories
    GROUP BY
        TopCategories
    HAVING COUNT(Year) = 1
),
results AS (
SELECT 
    rc.Year, 
    rc.Category, 
    rc.PercentageOfAnnualRoadIncidents
FROM 
    UniqueYear u
JOIN 
    RankedCategories rc ON u.Year = rc.Year
WHERE 
    rc.Rank <= 2
)

SELECT distinct Year FROM results;
-- name: local017_top2_per_year
with t as (select substr(collision_date,1,4) y, pcf_violation_category c, count(*) n,
  row_number() over (partition by substr(collision_date,1,4) order by count(*) desc) r from collisions group by 1,2)
select y, group_concat(c||' '||n, ' | ') from (select * from t where r<=2 order by y, r) group by y order by y;
-- name: local018_shares
with a as (select substr(collision_date,1,4) y, count(*) tot from collisions group by 1),
 top as (select pcf_violation_category c from collisions where substr(collision_date,1,4)='2021' group by 1 order by count(*) desc limit 1),
 s as (select substr(collision_date,1,4) y, 100.0*count(*)/(select tot from a where a.y=substr(collision_date,1,4)) share from collisions where pcf_violation_category=(select c from top) and substr(collision_date,1,4) in ('2011','2021') group by 1)
select (select c from top) cat, max(case when y='2011' then share end) s2011, max(case when y='2021' then share end) s2021,
 round(max(case when y='2011' then share end) - max(case when y='2021' then share end), 6) diff_2011_minus_2021 from s;
-- name: local015_helmet
with p as (select distinct c.case_id, c.motorcyclist_killed_count k,
   case when p.party_safety_equipment_1 like '%motorcycle helmet used%' or p.party_safety_equipment_2 like '%motorcycle helmet used%' then 'helmet_used'
        when p.party_safety_equipment_1 like '%motorcycle helmet not used%' or p.party_safety_equipment_2 like '%motorcycle helmet not used%' then 'helmet_not_used' end g
   from collisions c join parties p on p.case_id=c.case_id where c.motorcycle_collision=1)
select g, count(*) collisions, sum(k) motorcyclist_fatalities, round(100.0*sum(k)/count(*),2) pct from p where g is not null group by g order by g;
-- name: local015_join_size
select count(*) motorcycle_collisions, sum(case_id in (select case_id from parties)) with_any_party from collisions where motorcycle_collision=1;

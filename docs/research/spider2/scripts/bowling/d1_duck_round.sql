-- DuckDB: does round(0.9*(200-165)) give 32 (as SQLite does) or 31?
SELECT 0.9*(200-165) AS f, round(0.9*(200-165)) AS duck_round_double, round(0.9::DECIMAL(2,1)*(200-165)) AS duck_round_decimal, (9*(200-165)+5)//10 AS int_rule;

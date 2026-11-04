-- local163: faculty whose salary is closest to their rank's average (rank, names, salary).
-- Gold SQL from xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/sql/local163.sql (trailing
-- spaces trimmed). It reproduces the single gold variant local163_a; both ASSC rows tie.
WITH AvgSalaries AS (
    SELECT
        facrank AS FacRank,
        AVG(facsalary) AS AvSalary
    FROM
        university_faculty
    GROUP BY
        facrank
),
SalaryDifferences AS (
    SELECT
        university_faculty.facrank AS FacRank,
        university_faculty.facfirstname AS FacFirstName,
        university_faculty.faclastname AS FacLastName,
        university_faculty.facsalary AS Salary,
        ABS(university_faculty.facsalary - AvgSalaries.AvSalary) AS Diff
    FROM
        university_faculty
    JOIN
        AvgSalaries ON university_faculty.facrank = AvgSalaries.FacRank
),
MinDifferences AS (
    SELECT
        FacRank,
        MIN(Diff) AS MinDiff
    FROM
        SalaryDifferences
    GROUP BY
        FacRank
)
SELECT
    s.FacRank,
    s.FacFirstName,
    s.FacLastName,
    s.Salary
FROM
    SalaryDifferences s
JOIN
    MinDifferences m ON s.FacRank = m.FacRank AND s.Diff = m.MinDiff;

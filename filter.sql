-- filter.sql: WHERE clause for rebuilding the candidates table.
-- Edit this file, then run `python -m autoapply.filter` to apply.

-- Location
j.country IN ('US', 'CA')

-- Employment type (NULLs pass — Greenhouse doesn't provide this)
AND (j.employment_type = 'full-time' OR j.employment_type IS NULL)

-- Salary cap (NULLs pass — most don't list salary)
AND (j.max_salary IS NULL OR j.max_salary <= 300000)

-- Title seniority excludes
AND j.title NOT LIKE '%senior%'
AND j.title NOT LIKE 'sr %'
AND j.title NOT LIKE '% sr %'
AND j.title NOT LIKE 'sr.%'
AND j.title NOT LIKE '% sr.%'
AND j.title NOT LIKE '% sr'
AND j.title NOT LIKE '%staff%'
AND j.title NOT LIKE '%principal%'
AND j.title NOT LIKE '%director%'
AND j.title NOT LIKE '%manager%'
AND j.title NOT LIKE '%lead %'
AND j.title NOT LIKE '%lead,%'
AND j.title NOT LIKE '%, lead'
AND j.title NOT LIKE '%vp,%'
AND j.title NOT LIKE '%vp %'
AND j.title NOT LIKE '%vice president%'
AND j.title NOT LIKE '%head of%'
AND j.title NOT LIKE '%phd%'
AND j.title NOT LIKE '%distinguished%'
AND j.title NOT LIKE '%expert%'
AND j.title NOT LIKE '%intern%'
AND j.title NOT LIKE '%cleared%'
AND j.title NOT LIKE '%ts/sci%'
AND j.title NOT LIKE '%clearance%'

-- Role includes (title keywords)
AND (
   j.title LIKE '%software engineer%'
   OR j.title LIKE '%software developer%'
   OR j.title LIKE '%backend%'
   OR j.title LIKE '%back end%'
   OR j.title LIKE '%back-end%'
   OR j.title LIKE '%fullstack%'
   OR j.title LIKE '%full stack%'
   OR j.title LIKE '%full-stack%'
   OR j.title LIKE '%frontend%'
   OR j.title LIKE '%front end%'
   OR j.title LIKE '%front-end%'
   OR j.title LIKE '%machine learning%'
   OR j.title LIKE '%ml engineer%'
   OR j.title LIKE '%ai engineer%'
   OR j.title LIKE '%data engineer%'
   OR j.title LIKE '%data scientist%'
   OR j.title LIKE '%data analyst%'
   OR j.title LIKE '%analytics engineer%'
   OR j.title LIKE '%devops%'
   OR j.title LIKE '%sre%'
   OR j.title LIKE '%site reliability%'
   OR j.title LIKE '%platform engineer%'
   OR j.title LIKE '%infrastructure engineer%'
   OR j.title LIKE '%security engineer%'
   OR j.title LIKE '%cloud engineer%'
   OR j.title LIKE '%solutions architect%'
   OR j.title LIKE '%solutions engineer%'
   OR j.title LIKE '%application developer%'
   OR j.title LIKE '%web developer%'
   OR j.title LIKE '%python developer%'
   OR j.title LIKE '%product engineer%'
   OR j.title LIKE '%founding engineer%'
   OR j.title LIKE '%systems engineer%'
   OR j.title LIKE '%forward deployed%'
   OR j.title LIKE '%research engineer%'
   OR j.title LIKE '%solution engineer%'
)

-- Company exclusions
AND j.company_name NOT LIKE '%spacex%'
AND j.company_name NOT LIKE '%Accenture Federal%'

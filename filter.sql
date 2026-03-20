-- filter.sql: WHERE clause for rebuilding the candidates table.
-- Edit this file, then run `python -m openapply.filter` to apply.
-- The SELECT columns, JOINs (including department_categories and
-- role_categories), and dedup JOINs are handled by filter.py.

-- Location
j.country IN ('US', 'CA')

-- Employment type (NULLs pass — Greenhouse doesn't provide this)
AND (j.employment_type = 'full-time' OR j.employment_type IS NULL)

-- Salary cap (NULLs pass — most don't list salary)
AND (j.max_salary IS NULL OR j.max_salary <= 300000)

-- Title excludes (seniority)
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

-- Department filter
AND dc.category IN ('engineering', 'data')

-- Role filter (replaces title-based non-software excludes)
AND rc.role IN ('swe', 'backend', 'fullstack', 'ml', 'ai',
                'data-eng', 'data-science', 'devops', 'platform', 'security')

-- Company exclusions
AND j.company_name NOT LIKE '%spacex%'
AND j.company_name NOT LIKE '%Accenture Federal%'

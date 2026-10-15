SELECT *
FROM {{ ref('annual_revenue_growth') }}
WHERE
    (is_comparable = FALSE AND yoy_growth_pct IS NOT NULL)
    OR
    (is_comparable = TRUE AND yoy_growth_pct IS NULL)
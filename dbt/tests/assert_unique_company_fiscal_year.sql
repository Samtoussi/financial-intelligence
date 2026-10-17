SELECT
    cik,
    fiscal_year,
    COUNT(*) AS row_count
FROM {{ ref('annual_revenue') }}
GROUP BY
    cik,
    fiscal_year
HAVING COUNT(*) > 1

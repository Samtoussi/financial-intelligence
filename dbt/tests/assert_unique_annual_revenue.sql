SELECT
    cik,
    start_date,
    end_date,
    COUNT(*) AS row_count
FROM {{ ref('annual_revenue') }}
GROUP BY
    cik,
    start_date,
    end_date
HAVING COUNT(*) > 1
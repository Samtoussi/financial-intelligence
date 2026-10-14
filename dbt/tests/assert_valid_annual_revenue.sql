SELECT *
FROM {{ ref('annual_revenue') }}
WHERE revenue_usd <= 0
   OR date_diff('day', start_date, end_date) NOT BETWEEN 330 AND 380
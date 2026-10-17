
SELECT
    cik,
    fiscal_year,
    revenue_usd,
    previous_year_revenue_usd,
    yoy_growth_pct
FROM {{ ref('annual_revenue_growth') }}
WHERE is_comparable = TRUE
  AND ABS(
      yoy_growth_pct -
      ROUND(
          (
              revenue_usd / previous_year_revenue_usd - 1
          ) * 100,
          2
      )
  ) > 0.01

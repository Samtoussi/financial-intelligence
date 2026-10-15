WITH annual_revenue AS (
    SELECT
        cik,
        fiscal_year,
        start_date,
        end_date,
        revenue_usd,
        source_concept
    FROM {{ ref('annual_revenue') }}
),

previous_year AS (
    SELECT
        *,
        LAG(fiscal_year) OVER (
            PARTITION BY cik
            ORDER BY fiscal_year
        ) AS previous_fiscal_year,

        LAG(revenue_usd) OVER (
            PARTITION BY cik
            ORDER BY fiscal_year
        ) AS previous_year_revenue_usd

    FROM annual_revenue
),

comparability AS (
    SELECT
        *,
        CASE
            WHEN previous_fiscal_year IS NULL THEN FALSE

            WHEN fiscal_year - previous_fiscal_year != 1 THEN FALSE

            -- Microsoft FY2016 uses a recast revenue value,
            -- while FY2015 uses the older accounting basis.
            WHEN cik = 789019 AND fiscal_year = 2016 THEN FALSE

            ELSE TRUE
        END AS is_comparable

    FROM previous_year
)

SELECT
    cik,
    fiscal_year,
    revenue_usd,
    previous_year_revenue_usd,

    CASE
        WHEN is_comparable
             AND previous_year_revenue_usd > 0
        THEN ROUND(
            (revenue_usd / previous_year_revenue_usd - 1) * 100,
            2
        )
        ELSE NULL
    END AS yoy_growth_pct,

    is_comparable

FROM comparability
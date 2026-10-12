-- Financial Intelligence
-- Historical Value Changes
--
-- Identifies changes in reported financial values across SEC filings.
-- A value change is not necessarily a formal accounting restatement.

WITH filing_values AS (
    SELECT DISTINCT
        cik,
        taxonomy,
        concept,
        unit,
        start_date,
        end_date,
        accession,
        filed_date,
        form,
        value
    FROM financial_observations
    WHERE form IN ('10-K', '10-Q')
      AND value IS NOT NULL
      AND filed_date IS NOT NULL
      AND accession IS NOT NULL
),

filing_conflicts AS (
    SELECT
        cik,
        taxonomy,
        concept,
        unit,
        start_date,
        end_date,
        accession
    FROM filing_values
    GROUP BY
        cik,
        taxonomy,
        concept,
        unit,
        start_date,
        end_date,
        accession
    HAVING COUNT(DISTINCT value) > 1
),

comparable_values AS (
    SELECT fv.*
    FROM filing_values fv
    WHERE NOT EXISTS (
        SELECT 1
        FROM filing_conflicts fc
        WHERE fv.cik = fc.cik
          AND fv.taxonomy = fc.taxonomy
          AND fv.concept = fc.concept
          AND fv.unit = fc.unit
          AND fv.start_date IS NOT DISTINCT FROM fc.start_date
          AND fv.end_date = fc.end_date
          AND fv.accession = fc.accession
    )
),

ordered_values AS (
    SELECT
        *,
        LAG(value) OVER (
            PARTITION BY
                cik,
                taxonomy,
                concept,
                unit,
                start_date,
                end_date
            ORDER BY filed_date, accession
        ) AS previous_value,

        LAG(accession) OVER (
            PARTITION BY
                cik,
                taxonomy,
                concept,
                unit,
                start_date,
                end_date
            ORDER BY filed_date, accession
        ) AS previous_accession,

        LAG(filed_date) OVER (
            PARTITION BY
                cik,
                taxonomy,
                concept,
                unit,
                start_date,
                end_date
            ORDER BY filed_date, accession
        ) AS previous_filed_date

    FROM comparable_values
)

SELECT
    cik,
    taxonomy,
    concept,
    unit,
    start_date,
    end_date,

    previous_value,
    value AS new_value,

    value - previous_value AS absolute_change,

    CASE
        WHEN previous_value != 0
        THEN ROUND(
            100.0 * (value - previous_value)
            / ABS(previous_value),
            2
        )
        ELSE NULL
    END AS percentage_change,

    previous_accession,
    accession AS new_accession,

    previous_filed_date,
    filed_date AS new_filed_date

FROM ordered_values
WHERE previous_value IS NOT NULL
  AND value IS DISTINCT FROM previous_value;

WITH revenue_observations AS (

    SELECT
        cik,
        concept,
        value AS revenue_usd,
        start_date,
        end_date,
        accession,
        filed_date,
        form,

        CASE concept
            WHEN 'RevenueFromContractWithCustomerExcludingAssessedTax' THEN 1
            WHEN 'SalesRevenueNet' THEN 2
            WHEN 'Revenues' THEN 3
        END AS concept_priority

    FROM main.financial_observations

    WHERE cik = 789019
      AND taxonomy = 'us-gaap'
      AND unit = 'USD'
      AND concept IN (
          'RevenueFromContractWithCustomerExcludingAssessedTax',
          'SalesRevenueNet',
          'Revenues'
      )
      AND form = '10-K'
      AND start_date IS NOT NULL
      AND date_diff('day', start_date, end_date) BETWEEN 330 AND 380

),

ranked_observations AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY cik, start_date, end_date
            ORDER BY
                concept_priority ASC,
                filed_date DESC,
                accession DESC
        ) AS observation_rank

    FROM revenue_observations

)

SELECT
    cik,
    year(end_date) AS fiscal_year,
    start_date,
    end_date,
    revenue_usd,
    concept AS source_concept,
    accession AS source_accession,
    filed_date AS source_filed_date

FROM ranked_observations

WHERE observation_rank = 1


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

        CASE
            -- Microsoft
            WHEN cik = 789019
                AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'
                THEN 1
            WHEN cik = 789019
                AND concept = 'SalesRevenueNet'
                THEN 2
            WHEN cik = 789019
                AND concept = 'Revenues'
                THEN 3

            -- Caterpillar
            WHEN cik = 18230
                AND concept = 'Revenues'
                THEN 1
            WHEN cik = 18230
                AND concept = 'SalesRevenueNet'
                THEN 2

            -- JPMorgan
            WHEN cik = 19617
                AND concept = 'Revenues'
                THEN 1
            WHEN cik = 19617
                AND concept = 'RevenuesNetOfInterestExpense'
                THEN 2
        END AS concept_priority

    FROM main.financial_observations

    WHERE cik IN (789019, 18230, 19617)
      AND taxonomy = 'us-gaap'
      AND unit = 'USD'
      AND form = '10-K'
      AND start_date IS NOT NULL
      AND date_diff('day', start_date, end_date) BETWEEN 330 AND 380
),

ranked_observations AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY cik, end_date
            ORDER BY
                concept_priority ASC,
                filed_date DESC,
                accession DESC,
                start_date DESC
        ) AS observation_rank

    FROM revenue_observations

    WHERE concept_priority IS NOT NULL
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


# Financial Intelligence

**A financial data engineering platform built on SEC EDGAR, Python, DuckDB, and dbt — laying the foundation for AI-powered financial research.**

> **Current release: V1 — Data Foundation**

## Overview

Financial data is more complicated than simply retrieving the latest reported numbers.

Companies use different accounting concepts, previously reported values can change in subsequent filings, and financial periods are not always directly comparable.

Financial Intelligence explores these challenges by building a structured, traceable financial data platform using public SEC filings.

The project is developed in stages:

- **V1 — Data Foundation:** Ingest, preserve, transform, and validate structured financial data.
- **V2 — Document Intelligence:** Process financial reports and make their contents searchable.
- **V3 — AI Assistant:** Combine structured metrics and filing evidence to answer financial questions.
- **V4 — Product & Operations:** Explore an interactive product and operational improvements.

V1 focuses on establishing a reliable data foundation before introducing document retrieval or AI components.

## Architecture

```text
                   SEC EDGAR
                   CompanyFacts
                        |
                        v
                 Python Ingestion
                Validation + Retries
                        |
                        v
                 BRONZE — Raw JSON
              Timestamped Snapshots
                 SHA-256 Metadata
                        |
                        v
                  SILVER — Data
                Python Normalization
                    Parquet
                    DuckDB
                        |
                        v
                 GOLD — Analytics
                       dbt
                  Annual Revenue
                   YoY Growth
                        |
                        v
                  Data Quality
                pytest + dbt tests
```

The platform uses a Bronze/Silver/Gold architecture:

- **Bronze** preserves original SEC responses and snapshot metadata.
- **Silver** normalizes financial observations into Parquet and DuckDB.
- **Gold** applies analytical rules for annual revenue and revenue growth.

A single Python entry point runs the full pipeline locally.

## Data Source

V1 uses the [SEC EDGAR CompanyFacts API](https://www.sec.gov/edgar/sec-api-documentation).

Three companies are currently configured:

| Company | Ticker | CIK |
|---|---|---|
| Microsoft | MSFT | 789019 |
| JPMorgan Chase | JPM | 19617 |
| Caterpillar | CAT | 18230 |

These companies were selected to explore different reporting characteristics and revenue accounting concepts.

CompanyFacts provides structured XBRL-derived financial observations, including reporting periods, filing dates, accession numbers, accounting concepts, and reported values.

## Data Pipeline

### Bronze — SEC Ingestion

Python retrieves and validates CompanyFacts responses from the SEC.

The ingestion layer includes:

- Company and CIK validation
- HTTP retry handling with exponential backoff
- Timestamped raw JSON snapshots
- SHA-256 content identifiers
- Snapshot metadata and observation counts

Raw data is stored under:

```text
data/raw/sec/companyfacts/<TICKER>/
```

The original responses are preserved to support reproducibility and historical investigation.

### Silver — Normalization and Storage

Nested CompanyFacts data is normalized into structured observations.

Important fields include:

- Company identifier (CIK)
- Accounting taxonomy and concept
- Reported value and unit
- Reporting period
- Filing date
- Accession number
- Filing form
- Source snapshot identifier

Processed observations are stored as Parquet and loaded into DuckDB.

```text
data/processed/companyfacts/
data/warehouse/financial_intelligence.duckdb
```

The warehouse tracks loaded snapshots and maintains the active dataset for each company.

Historical filing observations remain available rather than being collapsed into a single latest value.

### Gold — Financial Analytics

dbt builds two analytical models.

**`main_gold.annual_revenue`**

Selects annual revenue observations from 10-K filings using company-specific accounting concept priorities.

The model deduplicates observations by company and fiscal year-end while retaining source information such as accounting concept, accession number, and filing date.

**`main_gold.annual_revenue_growth`**

Calculates year-over-year revenue growth and includes an `is_comparable` flag.

Growth is excluded when the previous fiscal year is missing, the periods are not consecutive, or an explicitly identified accounting comparability issue applies.

Example query:

```sql
SELECT
    cik,
    fiscal_year,
    revenue_usd,
    previous_year_revenue_usd,
    yoy_growth_pct,
    is_comparable
FROM main_gold.annual_revenue_growth
ORDER BY cik, fiscal_year DESC;
```

## V1 Engineering Findings

### 1. Historical Financial Values Can Change

SEC CompanyFacts may contain multiple reported values for the same accounting concept and reporting period.

During development, Microsoft financial observations revealed historical changes across subsequent filings.

This demonstrated why simply keeping the latest value would remove important reporting history.

**Engineering decision:** Preserve filing-level observations and source metadata in Silver, then apply explicit selection rules in Gold.

### 2. Revenue Is Not One Universal Accounting Concept

Microsoft, JPMorgan Chase, and Caterpillar do not consistently use the same revenue accounting concepts.

For example, the Gold model considers:

- Microsoft's `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, and `Revenues`
- Caterpillar's `Revenues` and `SalesRevenueNet`
- JPMorgan Chase's `Revenues` and `RevenuesNetOfInterestExpense`

A generic revenue extraction rule would not reliably represent all three companies.

**Engineering decision:** Use explicit company-specific concept priorities and retain the selected source concept for traceability.

### 3. Valid Arithmetic Does Not Guarantee Valid Comparisons

Microsoft FY2016 exposed an accounting comparability issue.

The selected FY2016 revenue observation reflects a different reporting basis from the selected FY2015 observation.

Calculating a percentage change between the two values would produce a mathematically valid but potentially misleading result.

**Engineering decision:** Mark FY2016 as non-comparable and return NULL for its year-over-year growth.

This is a targeted safeguard, not a comprehensive accounting restatement detection system.

### 4. Analytical Models Must Handle Repeated Filing Periods

Historical SEC observations can contain multiple candidate records for the same fiscal year-end, including different filing dates or reporting period starts.

Without appropriate deduplication, annual revenue models can produce multiple rows for one company and fiscal year.

**Engineering decision:** Rank candidate observations by accounting concept priority and filing metadata, selecting one annual record per company and fiscal year-end.

Automated dbt tests enforce uniqueness.

## Verified V1 Results

The first successful end-to-end pipeline execution was completed on October 17, 2026.

| Metric | Result |
|---|---:|
| Companies | 3 |
| Microsoft observations | 32,671 |
| JPMorgan Chase observations | 54,089 |
| Caterpillar observations | 39,403 |
| Total observations | 126,163 |
| Gold models | 2 |
| dbt data tests | 16 |
| dbt build | 18/18 passed |
| End-to-end runtime | 9.49 seconds |

The observation counts and runtime reflect one verified local execution. They are not fixed characteristics of future SEC responses.

## Data Quality and CI

V1 includes Python and dbt testing.

Python tests cover normalization, historical observation behavior, and snapshot lifecycle handling.

dbt tests validate:

- Required analytical fields
- Unique annual observations
- Valid revenue records
- Year-over-year growth calculations
- Comparability rules

GitHub Actions runs on pushes and pull requests targeting `main`.

The CI workflow installs dependencies, runs Python tests, creates a synthetic DuckDB dataset, and executes `dbt build`.

The synthetic dataset tests representative accounting and filing scenarios without depending on live SEC API responses.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | SEC ingestion and financial data processing |
| Requests | SEC API communication |
| JSON | Raw snapshot preservation |
| PyArrow / Parquet | Columnar processed data |
| DuckDB | Local analytical warehouse |
| dbt | Gold transformation and data tests |
| pytest | Python testing |
| GitHub Actions | Continuous integration |

## Engineering Decisions

### Why Preserve Historical Snapshots?

Financial disclosures can be revised or supplemented in later filings.

Preserving raw snapshots and filing-level observations makes it possible to investigate historical differences instead of silently replacing earlier information.

### Why DuckDB and Parquet?

V1 processes a relatively small analytical workload.

DuckDB and Parquet provide the required storage and analytical capabilities without managed database infrastructure or recurring cloud costs.

### Why dbt?

Python handles ingestion and normalization, while dbt handles analytical business rules.

This separates source-data processing from revenue selection, comparability logic, and analytical validation.

## Getting Started

### Requirements

- Python 3.13
- Git
- Internet connection
- SEC User-Agent with a real contact email

### Clone and Install

```bash
git clone https://github.com/Samtoussi/financial-intelligence.git
cd financial-intelligence

python -m venv .venv
```

Activate the environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

### Configure SEC User-Agent

Windows PowerShell:

```powershell
$env:SEC_USER_AGENT = "FinancialIntelligence your-email@example.com"
```

macOS/Linux:

```bash
export SEC_USER_AGENT="FinancialIntelligence your-email@example.com"
```

Replace the example address with your own contact email.

### Run the Pipeline

```bash
python run_pipeline.py
```

This runs SEC ingestion, Bronze snapshot storage, Silver normalization and loading, and the dbt Gold build.

### Run Tests

Python:

```bash
python -m pytest tests -v
```

dbt (after the warehouse has been populated):

```bash
dbt build --project-dir dbt --profiles-dir dbt
```

## Repository Structure

```text
financial-intelligence/
├── .github/
│   └── workflows/
│       └── ci.yml
├── dbt/
│   ├── models/
│   │   └── gold/
│   │       ├── annual_revenue.sql
│   │       ├── annual_revenue_growth.sql
│   │       └── schema.yml
│   ├── tests/
│   ├── dbt_project.yml
│   └── profiles.yml
├── scripts/
│   └── create_ci_db.py
├── src/
│   ├── ingestion/
│   │   └── companyfacts.py
│   └── transformation/
│       └── load_companyfacts.py
├── tests/
├── requirements.txt
├── run_pipeline.py
└── README.md
```

Local datasets, databases, generated artifacts, and secrets are excluded from version control.

## Limitations

V1 intentionally focuses on structured financial data.

Current limitations:

- Three configured companies
- Annual revenue and revenue growth as the initial Gold analytics
- Company-specific revenue selection rules
- Partial accounting comparability handling
- Local, on-demand pipeline execution
- No document retrieval or AI assistant yet

The project is an engineering portfolio project, not an investment advisory service.

## Version History

### V1 — Data Foundation

Established a reproducible SEC financial data pipeline with historical preservation, structured analytics, automated testing, and continuous integration.

**Core question:** Can we build a trustworthy and traceable financial data foundation?

### V2 — Document Intelligence

Planned: financial filing ingestion, document processing, and source-grounded retrieval.

**Core question:** Can we retrieve reliable evidence from financial reports?

### V3 — AI Assistant

Planned: natural-language financial analysis combining structured metrics and relevant filing evidence.

**Core question:** Can AI answer financial questions with verifiable sources?

### V4 — Product & Operations

Potential interactive interface, deployment, and operational improvements based on demonstrated needs.

**Core question:** Can we turn the underlying intelligence into a useful, reliable product?

## Project Philosophy

Financial Intelligence follows a simple engineering principle:

**Build the smallest system that solves the current problem, then evolve it when new requirements justify additional complexity.**

V1 establishes the data foundation.

Future versions will introduce document intelligence and AI capabilities only when the underlying data and retrieval systems can support them reliably.

> **The goal is not to attach AI to a dashboard. It is to build a financial intelligence system whose answers can be traced back to evidence.**

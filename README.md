
# Financial Intelligence

**A traceable financial data engineering platform built on SEC EDGAR, Python, DuckDB, dbt, and document retrieval — laying the foundation for evidence-grounded AI financial research.**

> **Current milestone: V2 — Document Intelligence (locally verified; release pending)**

## Overview

Financial research requires more than retrieving the latest reported numbers.

Companies use different accounting concepts, historical financial values can change in subsequent filings, and important business context often exists in narrative disclosures rather than structured tables.

Financial Intelligence explores these challenges by building a financial data platform that combines structured financial observations with searchable SEC filings.

The project is developed incrementally:

- **V1 — Data Foundation:** Ingest, preserve, transform, and validate structured financial data.
- **V2 — Document Intelligence:** Process SEC annual reports and make their contents searchable.
- **V3 — AI Assistant:** Combine structured metrics and filing evidence to answer financial questions.
- **V4 — Product & Operations:** Explore an interactive product and operational improvements.

The platform currently runs locally without managed cloud infrastructure.

## Architecture

Financial Intelligence consists of two independent data pipelines.

```text
                         SEC EDGAR
                             |
               +-------------+-------------+
               |                           |
         CompanyFacts API             10-K Filings
               |                           |
         Python Ingestion             HTML Ingestion
               |                           |
               v                           v
         BRONZE — JSON               BRONZE — HTML
         Raw Snapshots               Raw Snapshots
         SHA-256 Metadata            SHA-256 Metadata
               |                           |
               v                           v
         SILVER — Data               Document Parsing
         Normalization               Item 1A / Item 7
         Parquet + DuckDB                  |
               |                           v
               v                     Structured Sections
         GOLD — Analytics            Parquet + SHA-256
         dbt Models                        |
         Annual Revenue                    v
         YoY Growth                  Document Chunking
               |                     Source Offsets
               v                           |
         Data Quality                      v
         pytest + dbt Tests          Parquet Chunks
                                           |
                                           v
                                     Lexical Retrieval
                                     Search CLI
```

The pipelines are intentionally separate.

The CompanyFacts pipeline processes structured financial observations, while the document pipeline processes narrative disclosures.

Both provide foundations for future evidence-grounded financial analysis.

## Data Sources

The platform uses public [SEC EDGAR data](https://www.sec.gov/edgar/sec-api-documentation).

Three companies are currently configured:

| Company | Ticker | CIK |
|---|---|---:|
| Microsoft | MSFT | 789019 |
| JPMorgan Chase | JPM | 19617 |
| Caterpillar | CAT | 18230 |

These companies were selected to explore different financial reporting characteristics, accounting concepts, and document structures.

---

# V2 — Document Intelligence

V2 extends Financial Intelligence beyond structured financial observations.

The objective is to retrieve, preserve, process, and search narrative information from SEC annual reports while maintaining traceability to the original source.

## 1. Bronze — SEC Filing Ingestion

The document pipeline discovers the latest available 10-K filing for a configured company using SEC submissions data.

It then downloads the primary filing document and preserves the original HTML response.

Raw filings are stored under:

```text
data/raw/sec/filings/<TICKER>/<ACCESSION>/
```

Each snapshot includes:

- Original HTML document
- Company ticker and CIK
- Filing accession number
- Filing and report dates
- SEC source URL
- Retrieval timestamp
- SHA-256 content hash
- File size

Snapshots use timestamped filenames and content-hash identifiers.

Preserving the original documents makes it possible to investigate extraction results against the exact source that was processed.

## 2. Silver — Document Parsing and Storage

The pipeline extracts two sections from each 10-K filing.

### Item 1A — Risk Factors

Contains disclosures about risks that may affect the company's operations, financial condition, or future performance.

### Item 7 — Management's Discussion and Analysis

Contains management's discussion of financial results, operating performance, and financial condition.

### Extraction Strategy

SEC filings do not follow one universal HTML structure.

The parser identifies section boundaries, extracts the relevant text, and normalizes whitespace.

It supports:

- Direct section extraction
- A referenced MD&A layout
- Section-length validation
- Extraction metadata
- Text integrity checks

JPMorgan Chase's 10-K presented a notable challenge: its Item 7 heading referenced MD&A content located elsewhere in the document.

The parser handles this supported layout rather than assuming that all content appears immediately after the Item 7 heading.

### Structured Storage

Extracted sections are stored as Parquet:

```text
data/processed/filings/<TICKER>/<ACCESSION>/sections.parquet
```

Each section retains:

- Ticker and CIK
- Filing accession number
- Filing and report dates
- SEC source URL
- Item number
- Extraction method
- Normalized text
- Character and word counts
- SHA-256 text hash

Parquet files are written to temporary files, verified, and atomically moved into place.

This reduces the risk of publishing incomplete processed output.

## 3. Document Chunking

Long filing sections are divided into smaller text segments for retrieval.

The chunking implementation:

- Targets approximately 300 words per chunk
- Enforces a maximum of 350 words
- Prefers sentence boundaries
- Falls back to word boundaries when necessary
- Preserves character offsets
- Generates deterministic chunk identifiers

Chunks retain source metadata, including ticker, accession number, Item number, source URL, and section hash.

Processed chunks are stored under:

```text
data/processed/filing_chunks/<TICKER>/chunks.parquet
```

### Text Integrity

Chunking is tested for exact reconstruction.

When the chunks are combined using their recorded positions, they reproduce the original normalized section text.

This verifies that the chunking process does not silently discard or alter document content.

## 4. Lexical Retrieval

V2 introduces a local retrieval system for searching processed SEC filings.

The retrieval implementation uses DuckDB to read Parquet chunks and Python-based lexical ranking.

Supported functionality includes:

- Query tokenization
- Case-insensitive matching
- Whole-word matching
- Requirement that all query terms appear
- Exact-phrase scoring bonus
- Term-frequency-based scoring
- Optional ticker filtering
- Deterministic result ordering

Example:

```bash
python -m src.retrieval.search_filings "interest rate risk" --limit 5
```

Search a specific company:

```bash
python -m src.retrieval.search_filings "cloud revenue" --ticker MSFT --limit 5
```

Results include source metadata and document text so retrieved evidence can be traced back to the relevant filing.

### Retrieval Evaluation

An initial retrieval baseline was created using representative financial queries:

- Interest rate risk
- Cloud revenue
- Credit losses
- Supply chain
- Foreign exchange

Evaluation output is stored locally at:

```text
data/evaluation/retrieval_baseline.csv
```

The baseline supports inspection of ranked results.

No manually verified relevance score or formal retrieval-quality benchmark is claimed.

V2 deliberately uses lexical retrieval rather than introducing embeddings, vector databases, or language models before they are required.

## 5. End-to-End Document Pipeline

The document workflow is integrated through a dedicated entry point:

```text
run_filings.py
```

Example execution:

```bash
python -m run_filings MSFT
```

The command performs:

1. SEC 10-K discovery
2. Filing download
3. Raw HTML snapshot preservation
4. Item 1A and Item 7 extraction
5. Section validation and Parquet storage
6. Document chunking
7. Searchable Parquet output

The original structured-data pipeline remains independent:

```bash
python run_pipeline.py
```

This separation allows document processing without rerunning CompanyFacts ingestion or dbt analytics.

## Verified V2 Results

Local end-to-end executions were completed on October 17, 2026.

| Company | Item 1A Words | Item 7 Words | Chunks | Runtime |
|---|---:|---:|---:|---:|
| Microsoft | 11,759 | 7,695 | 64 | 2.84s |
| JPMorgan Chase | 15,906 | 59,379 | 253 | 9.10s |
| Caterpillar | 7,913 | 16,115 | 79 | 2.95s |
| **Total** | **35,578** | **83,189** | **396** | **14.89s** |

All six target sections were extracted successfully.

Five sections used direct extraction. JPMorgan Chase's Item 7 required referenced-MD&A extraction.

Exact chunk reconstruction was verified for all six sections.

### Automated Tests

The local test suite completed with:

```text
45 passed, 3 warnings
```

The three warnings are BeautifulSoup `XMLParsedAsHTMLWarning` messages encountered while parsing SEC filing documents containing inline-XBRL markup.

They did not cause test failures.

V2's local validation is complete. GitHub Actions verification remains a release checkpoint.

The reported runtimes and chunk counts reflect these specific local executions and documents.

## V2 Engineering Findings

### 1. Financial Documents Are Not Structurally Uniform

A parser that assumes identical HTML layouts across companies can fail even when the filings contain the required information.

JPMorgan Chase's referenced MD&A section demonstrated this problem.

**Engineering decision:** Support the observed alternative document layout while keeping the extraction logic explicit and testable.

### 2. Document Processing Must Preserve Traceability

Extracting text is not sufficient if the resulting passages cannot be connected to their source.

**Engineering decision:** Retain filing identifiers, source URLs, section hashes, deterministic chunk IDs, and character offsets throughout processing.

### 3. Chunking Must Preserve Information

Text splitting can accidentally introduce gaps, overlaps, or altered content.

**Engineering decision:** Test exact reconstruction of the normalized source text rather than validating chunk sizes alone.

### 4. Retrieval Does Not Initially Require an LLM

A retrieval system can be built and tested independently of a language model.

**Engineering decision:** Establish lexical retrieval before introducing semantic search or AI-generated answers.

### 5. Reliable Processing Requires Safe Storage

Partial writes can leave processed datasets in an inconsistent state.

**Engineering decision:** Preserve raw filing snapshots and use verified, atomic Parquet writes for processed sections.

---

# V1 — Data Foundation

V1 established the structured financial-data pipeline.

It processes SEC CompanyFacts observations through Bronze, Silver, and Gold layers.

## Bronze — SEC CompanyFacts Ingestion

Python retrieves and validates CompanyFacts responses from SEC EDGAR.

The ingestion layer includes:

- Company and CIK validation
- HTTP retry handling with exponential backoff
- Timestamped raw JSON snapshots
- SHA-256 content identifiers
- Snapshot metadata and observation counts

Raw responses are stored under:

```text
data/raw/sec/companyfacts/<TICKER>/
```

Original responses are preserved to support reproducibility and investigation of historical reporting changes.

## Silver — Normalization and Storage

Nested CompanyFacts data is normalized into structured financial observations.

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

## Gold — Financial Analytics

dbt builds two analytical models.

### `main_gold.annual_revenue`

Selects annual revenue observations from 10-K filings using company-specific accounting-concept priorities.

The model deduplicates observations by company and fiscal year-end while retaining the selected accounting concept and filing metadata.

### `main_gold.annual_revenue_growth`

Calculates year-over-year revenue growth and includes an `is_comparable` flag.

Growth is excluded when:

- The previous fiscal year is missing
- Reporting periods are not consecutive
- An explicitly identified accounting comparability issue applies

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

During development, Microsoft observations revealed historical changes across subsequent filings.

Simply keeping the latest reported value would remove important reporting history.

**Engineering decision:** Preserve filing-level observations and source metadata in Silver, then apply explicit selection rules in Gold.

### 2. Revenue Is Not One Universal Accounting Concept

Microsoft, JPMorgan Chase, and Caterpillar do not consistently use the same revenue accounting concepts.

The Gold model considers company-specific concepts, including:

- Microsoft: `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, and `Revenues`
- Caterpillar: `Revenues` and `SalesRevenueNet`
- JPMorgan Chase: `Revenues` and `RevenuesNetOfInterestExpense`

A generic revenue extraction rule would not reliably represent all three companies.

**Engineering decision:** Use explicit company-specific concept priorities and retain the selected source concept for traceability.

### 3. Valid Arithmetic Does Not Guarantee Valid Comparisons

Microsoft FY2016 exposed an accounting comparability issue.

The selected FY2016 revenue observation reflects a different reporting basis from the selected FY2015 observation.

Calculating percentage growth between the two values would produce a mathematically valid but potentially misleading result.

**Engineering decision:** Mark FY2016 as non-comparable and return NULL for its year-over-year growth.

This is a targeted safeguard, not a comprehensive accounting restatement detection system.

### 4. Analytical Models Must Handle Repeated Filing Periods

Historical SEC observations can contain multiple candidate records for the same fiscal year-end.

Without deduplication, annual revenue models may produce multiple rows for one company and fiscal year.

**Engineering decision:** Rank candidate observations by accounting-concept priority and filing metadata, selecting one annual record per company and fiscal year-end.

Automated dbt tests enforce uniqueness.

## Verified V1 Results

The first verified end-to-end V1 execution was completed on October 17, 2026.

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

These results reflect one verified local execution, not fixed characteristics of future SEC responses.

---

## Data Quality and CI

Financial Intelligence uses automated testing across both pipelines.

### Python Tests

Tests cover:

- CompanyFacts normalization
- Historical observation handling
- Snapshot lifecycle
- Filing extraction
- Section validation and storage
- Chunking and text reconstruction
- Lexical retrieval

Run locally:

```bash
python -m pytest tests -v
```

### dbt Tests

dbt validates:

- Required analytical fields
- Unique annual observations
- Valid revenue records
- Year-over-year growth calculations
- Comparability rules

Run:

```bash
dbt build --project-dir dbt --profiles-dir dbt
```

### Continuous Integration

GitHub Actions was introduced in V1.

The CI workflow installs dependencies, runs Python tests, creates a synthetic DuckDB dataset, and executes `dbt build`.

The synthetic dataset tests representative financial scenarios without requiring live SEC CompanyFacts requests.

V2 has passed its local test suite. The updated GitHub Actions workflow must be verified before tagging the V2 release.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Ingestion and data processing |
| Requests | SEC API and HTTP communication |
| BeautifulSoup / lxml | SEC HTML parsing |
| JSON | Raw SEC data and snapshot metadata |
| PyArrow / Parquet | Columnar storage |
| DuckDB | Local warehouse and Parquet-backed retrieval |
| dbt | Financial analytics and data tests |
| pytest | Automated testing |
| GitHub Actions | Continuous integration |

## Getting Started

### Requirements

- Python 3.12 or a compatible version supported by the dependencies
- Git
- Internet connection for SEC ingestion
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

SEC requests require an identifying application name and a real contact email.

Windows PowerShell:

```powershell
$env:SEC_USER_AGENT = "FinancialIntelligence your-email@example.com"
```

macOS/Linux:

```bash
export SEC_USER_AGENT="FinancialIntelligence your-email@example.com"
```

Replace the example address with your own contact email.

### Run the Structured Data Pipeline

```bash
python run_pipeline.py
```

This runs CompanyFacts ingestion, Bronze snapshot storage, Silver normalization and loading, and the dbt Gold build.

### Run the Document Pipeline

```bash
python -m run_filings MSFT
```

Other configured companies:

```bash
python -m run_filings JPM
python -m run_filings CAT
```

The document pipeline downloads the latest available 10-K, extracts Item 1A and Item 7, stores the sections, and builds searchable chunks.

### Search SEC Filings

```bash
python -m src.retrieval.search_filings "interest rate risk" --limit 5
```

Filter by company:

```bash
python -m src.retrieval.search_filings "cloud revenue" --ticker MSFT --limit 5
```

The document pipeline must be run first to generate the local searchable dataset.

### Run Tests

Python:

```bash
python -m pytest tests -v
```

dbt:

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
│   │   ├── companyfacts.py
│   │   └── filings.py
│   ├── transformation/
│   │   ├── load_companyfacts.py
│   │   ├── parse_filings.py
│   │   ├── store_filings.py
│   │   └── chunk_filings.py
│   └── retrieval/
│       ├── search_filings.py
│       └── evaluate.py
├── tests/
├── requirements.txt
├── run_pipeline.py
├── run_filings.py
└── README.md
```

Local datasets, generated artifacts, databases, and secrets are excluded from version control.

## Limitations

The current platform intentionally has a limited scope.

- Three companies are configured.
- The demonstrated document workflow processes the latest available 10-K for each company.
- Document extraction targets Item 1A and Item 7 only.
- Additional filing layouts may require parser improvements.
- Retrieval is lexical rather than semantic.
- No formal, manually labeled retrieval relevance benchmark has been established.
- Financial analytics focus on annual revenue and year-over-year growth.
- Accounting comparability handling is partial and explicitly scoped.
- Pipelines run locally on demand.
- No hosted application or continuous ingestion service is provided.
- No LLM-powered financial assistant is implemented yet.

Financial Intelligence is an engineering portfolio project, not an investment advisory service.

## Version History

### V1 — Data Foundation

Established a reproducible SEC financial data pipeline with historical preservation, structured analytics, automated testing, and continuous integration.

**Core question:** Can we build a trustworthy and traceable financial data foundation?

### V2 — Document Intelligence

Added SEC 10-K ingestion, raw document preservation, narrative section extraction, structured Parquet storage, deterministic chunking, and source-traceable lexical retrieval.

Verified end-to-end processing for Microsoft, JPMorgan Chase, and Caterpillar.

**Core question:** Can we retrieve traceable evidence from financial reports?

### V3 — AI Assistant (Planned)

Explore natural-language financial analysis that combines structured financial metrics with retrieved filing evidence.

The objective is to produce answers that can be checked against original financial disclosures.

**Core question:** Can AI answer financial questions with verifiable sources?

### V4 — Product & Operations (Potential)

Explore an interactive interface, deployment, monitoring, and operational improvements where justified by actual requirements.

**Core question:** Can the underlying intelligence become a useful and reliable product?

## Project Philosophy

Financial Intelligence follows a simple engineering principle:

**Build the smallest system that solves the current problem, then evolve it when new requirements justify additional complexity.**

V1 establishes structured financial data.

V2 introduces searchable narrative evidence.

V3 can build on both foundations without introducing AI prematurely.

> **The goal is not to attach AI to a dashboard. It is to build a financial intelligence system whose answers can be traced back to evidence.**

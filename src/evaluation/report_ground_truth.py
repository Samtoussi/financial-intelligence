"""Profile-aware report oracle validation. The separate M001 validator is unchanged."""
from decimal import Decimal
from pathlib import Path
import re
from src.analytics.report_profiles import DEFAULT_PROFILE, get_profile
from src.evaluation.ground_truth import load_dataset, number, require, citation, yoy


def load_report_dataset(profile=DEFAULT_PROFILE, path=None):
    config = get_profile(profile)
    return load_dataset(path or Path(__file__).resolve().parents[2] / "evals/ground_truth" / config["ground_truth"])


def validate_report_dataset(data, profile=DEFAULT_PROFILE):
    try:
        return _validate(data, get_profile(profile))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Missing or malformed report dataset: {exc}") from exc


def _validate(data, config):
    report, metrics = config["report"], config["metrics"]
    require(data["schema_version"] == 1 and data["milestone"] == ("M005" if config.get('contract') else "M001" if config["id"] == DEFAULT_PROFILE else "M003"), "invalid schema")
    expected = {k:report[k] for k in ("form", "fiscal_period", "period_end", "filing_date", "accession", "source_url")}
    expected.update(company=config.get('company', "Microsoft Corporation"), cik=f"{report['cik']:010d}")
    require(all(data["report"].get(k) == v for k,v in expected.items()), "inconsistent report metadata")
    citation(data["report"]["filing_date_source"], ("url", "section", "location"),
             "https://microsoft.gcs-web.com/financial-information/sec-filings" if config["id"] == DEFAULT_PROFILE else report["source_url"].replace(report["document"], report["accession"] + "-index.html"))
    periods = {
        "current": {"fiscal_period":report["fiscal_period"], "start":report["period_start"], "end":report["period_end"]},
        "prior": {"fiscal_period":config.get('prior_fiscal_period', f"FY{int(report['fiscal_period'][2:6])-1} Q1"), "start":report["prior_start"], "end":report["prior_end"]},
    }
    require(data["periods"] == periods, "inconsistent report periods")
    entries = data["metrics"]
    ids = [m["id"] for m in entries]
    require(len(ids) == len(set(ids)) and set(ids) == set(metrics), "missing, duplicate or unexpected metric IDs")
    values, changes = {}, {}
    for m in entries:
        mid = m["id"]
        require((m["unit"], m["gaap_status"]) == metrics[mid][1:], "inconsistent metric units or GAAP basis")
        citation(m["source"], ("url", "section", "table", "row", "columns"), report["source_url"])
        require(type(m["source"].get("page")) is int and m["source"]["page"] > 0, "missing citation page")
        expected_row = metrics[mid][0] + " / Revenue" if mid.endswith("_revenue") else metrics[mid][0]
        require(m["source"]["row"] == (metrics[mid][0] if config.get('bindings') else "Earnings per share / Diluted" if mid == "diluted_eps" else expected_row), "incorrect source row")
        columns = (f"Three Months Ended March 31: {report['period_end'][:4]} / {report['prior_end'][:4]}" +
                   ('; Total Sales and Revenues (including intersegment)' if config['bindings'][mid]['role'] == 'segment' else '')) if config.get('bindings') else f"Three Months Ended September 30: {report['period_end'][:4]} / {report['prior_end'][:4]}"
        require(m["source"]["columns"] == columns, "incorrect source columns")
        values[mid] = {}
        for period in periods:
            obs = m[period]
            require(obs["period"] == periods[period], "inconsistent metric periods")
            value = number(obs["value"])
            require(value == value.quantize(Decimal('0.01' if mid == 'diluted_eps' else '1')), "invalid value precision for unit")
            values[mid][period] = value
        changes[mid] = yoy(m["current"]["value"], m["prior"]["value"])
    if config.get('reconciliation_rows'):
        from src.analytics.report_tables import check_reconciliation
        rows = data['reconciliation']
        require([r['label'] for r in rows] == config['reconciliation_rows'], 'incorrect reconciliation rows')
        for r in rows:
            citation(r['source'], ('url', 'section', 'table', 'row', 'columns'), report['source_url'])
            require(r['source']['row'] == r['label'] and r['source']['page'] == 27, 'incorrect reconciliation location')
            for column in ('external', 'intersegment', 'total'):
                require(len(r[column]) == 2 and all(isinstance(v, str) and re.fullmatch(r'-?\d+', v) for v in r[column]), 'invalid reconciliation values')
        check_reconciliation(rows, [values['revenue'][p] for p in periods])
        for mid, b in config['bindings'].items():
            if b['role'] == 'segment':
                r = next(r for r in rows if r['label'] == metrics[mid][0])
                require([values[mid][p] for p in periods] == [Decimal(v) for v in r['total']], 'segment oracle mismatch')
    for period in (() if config.get('reconciliation_rows') else periods):
        require(sum(values[mid][period] for mid in metrics if mid.endswith("_revenue")) == values["revenue"][period], "incorrect segment total")
        require(values["net_income"][period] <= values["operating_income"][period] <= values["revenue"][period], "inconsistent income ordering")
    cases = data["qualitative_review_cases"]
    require(len(cases) == len(config["topics"]) and {c["id"] for c in cases} == set(config["topics"]), "invalid qualitative cases")
    for case in cases:
        require(case["status"] == "pending_manual_review" and case["conclusion"] is None, "oracle conclusions require manual review")
        require(isinstance(case["question"], str) and case["question"].strip(), "missing review question")
        require(case["evidence_locations"], "missing review evidence locations")
        for e in case["evidence_locations"]:
            citation(e, ("url", "section", "location"), report["source_url"])
            require(type(e.get("page")) is int and e["page"] > 0, "missing evidence page")
    return changes

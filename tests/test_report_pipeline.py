"""M002 runs offline with synthetic HTML and controlled model responses."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pyarrow.parquet as pq
import pytest

from src.ai.report_generator import generate_report, render_report, SCHEMA
from src.analytics.report_evidence import REPORT, METRICS, NOTE_IDS, build_report_evidence
from src.evaluation.ground_truth import load_dataset, yoy
from src.evaluation.report_evaluation import evaluate_report
from src.ingestion import filings
from src.retrieval import search_filings as search_module
from src.transformation import parse_filings, store_filings, chunk_filings


def sample_html():
    # Test-only representative cells; production evidence never uses ground truth.
    rows = """<tr><td>Three Months Ended September 30,</td><td>2026</td><td>2025</td></tr>
    <tr><td>Total revenue</td><td>92,279</td><td>77,673</td></tr>
    <tr><td>Operating income</td><td>45,915</td><td>37,961</td></tr>
    <tr><td>Net income</td><td>36,629</td><td>27,747</td></tr>
    <tr><td>Diluted</td><td>4.92</td><td>3.72</td></tr>"""
    return ("""<html><body><nav>
    <a href="#statements">Financial Statements</a>
    <a href="#mda">Management’s Discussion and Analysis of Financial Condition and Results of Operations</a>
    <a href="#market">Quantitative and Qualitative Disclosures About Market Risk</a></nav>
    <div id="statements">ITEM 1. FINANCIAL STATEMENTS</div>
    <p>INCOME STATEMENTS (In millions, except per share amounts) (Unaudited)</p><table>""" + rows + """</table>
    <p>Refer to accompanying notes.</p><p>Recast of Certain Prior Period Information</p>
    <p>Prior period segment information has been recast to conform to the current structure.</p>
    <p>Estimates and Assumptions</p><p>""" + "Accounting policies. " * 35 + """</p>
    <p>Segment revenue, cost of revenue, operating expenses, and operating income were as follows:</p>
    <p>(In millions)</p><table>
    <tr><td>Three Months Ended September 30,</td><td>2026</td><td>2025</td></tr>
    <tr><td>Agents and Infra</td></tr><tr><td>Revenue</td><td>76,795</td><td>61,672</td></tr>
    <tr><td>Devices and Consumer</td></tr><tr><td>Revenue</td><td>15,484</td><td>16,001</td></tr>
    </table><p>No sales to an individual country accounted for more than 10%.</p>
    <div id="mda">ITEM 2. MANAGEMENT DISCUSSION</div><p>SUMMARY RESULTS OF OPERATIONS</p>
    <p>Adjusted net income and EPS are non-GAAP measures.</p>
    <p>Microsoft Cloud gross margin percentage decreased to 66%. Azure revenue increased 48%.</p>
    <p>""" + "Management discussion. " * 35 + """</p><div>OPERATING EXPENSES</div>
    <p>Expenses discussion.</p><div id="market">ITEM 3. MARKET RISK</div>
    <p>MARKET_ONLY</p><div>PART II</div><div>Item 1. LEGAL_ONLY</div></body></html>""").encode("utf-8")


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    monkeypatch.setattr(filings, "RAW_DIR", raw)
    monkeypatch.setattr(parse_filings, "RAW_DIR", raw)
    filing = {k: REPORT[k] for k in ("cik", "form", "accession", "filing_date", "document", "source_url")}
    filing["report_date"] = REPORT["period_end"]
    snapshot = filings.save_snapshot("MSFT", sample_html(), filing)
    sections = store_filings.prepare_sections("MSFT", form="10-Q", accession=REPORT["accession"], snapshot_path=snapshot)
    _, metadata = parse_filings.load_latest_snapshot("MSFT", form="10-Q", accession=REPORT["accession"])
    evidence = build_report_evidence(sections, metadata)
    gt = load_dataset()
    by_label = {e["label"]: e for e in evidence}
    metrics = []
    for m in gt["metrics"]:
        e = by_label["segment_table" if m["id"].endswith("_revenue") else "income_statement"]
        metrics.append({"id": m["id"], "current": m["current"]["value"], "prior": m["prior"]["value"],
                        "unit": m["unit"], "gaap_status": m["gaap_status"],
                        "yoy_percent": yoy(m["current"]["value"], m["prior"]["value"]),
                        "citations": [{"evidence_id": e["evidence_id"], "quote": e["text"]}]})
    notes = []
    for nid in NOTE_IDS:
        e = by_label["recast_disclosure" if nid == NOTE_IDS[1] else "management_summary"]
        notes.append({"id": nid, "text": "A controlled interpretation for manual review.",
                      "citations": [{"evidence_id": e["evidence_id"], "quote": e["text"]}]})
    report = {"report": {k: REPORT[k] for k in SCHEMA["schema"]["properties"]["report"]["properties"]},
              "metrics": metrics, "notes": notes}
    return SimpleNamespace(snapshot=snapshot, sections=sections, evidence=evidence, gt=gt,
                           metadata=metadata, report=report)


def evaluate(bundle, report=None, evidence=None, **kwargs):
    return evaluate_report(report if report is not None else bundle.report,
                           evidence if evidence is not None else bundle.evidence,
                           bundle.gt, source_sha256=bundle.metadata["sha256"], **kwargs)


def test_quarterly_boundaries_and_table_context(bundle):
    assert {s["item"] for s in bundle.sections} == {"I.1", "I.2"}
    assert all("MARKET_ONLY" not in s["text"] and "LEGAL_ONLY" not in s["text"] for s in bundle.sections)
    text = bundle.sections[0]["text"]
    assert "| Total revenue | 92,279 | 77,673" in text
    for term in ("September 30", "2026", "2025", "millions", "per share"):
        assert term in text
    for e in bundle.evidence:
        section = next(s for s in bundle.sections if s["item"] == e["item"])
        assert section["text"][e["start_char"]:e["end_char"]] == e["text"]
        assert e["chunk_ids"]


def test_snapshot_selection_never_switches_filings(bundle):
    other = {**bundle.metadata, "accession": "0001193125-26-999999"}
    filings.save_snapshot("MSFT", b"Newer unrelated filing", other)
    payload, meta = parse_filings.load_latest_snapshot("MSFT", form="10-Q", accession=REPORT["accession"])
    assert meta["accession"] == REPORT["accession"] and payload == sample_html()
    with pytest.raises(ValueError, match="matching"):
        parse_filings.load_latest_snapshot("MSFT", form="10-K", snapshot_path=bundle.snapshot)
    with pytest.raises(ValueError, match="accession"):
        parse_filings.load_latest_snapshot("MSFT", accession="../escape")


def test_annual_snapshot_default_ignores_quarterly_snapshot(bundle):
    annual = {**bundle.metadata, "form": "10-K", "accession": "0001193125-26-323660"}
    path = filings.save_snapshot("MSFT", b"annual snapshot", annual)
    payload, meta = parse_filings.load_latest_snapshot("MSFT")
    assert payload == path.read_bytes() and meta["form"] == "10-K"


def test_snapshot_checksum_failure(bundle):
    bundle.snapshot.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        parse_filings.load_latest_snapshot("MSFT", form="10-Q", snapshot_path=bundle.snapshot)


def test_ambiguous_quarterly_destination_rejected():
    soup = parse_filings.parse_html(sample_html().replace(b'id="mda"', b'id="statements"'))
    with pytest.raises(ValueError, match="destination"):
        parse_filings.quarterly_boundaries(soup)


def test_reversed_quarterly_boundaries_rejected():
    soup = parse_filings.parse_html(sample_html())
    starts = parse_filings.quarterly_boundaries(soup)
    with pytest.raises(ValueError, match="boundaries"):
        parse_filings.quarterly_text(soup, starts[1], starts[0])


def test_missing_metric_evidence_fails_closed(bundle):
    bundle.sections[0]["text"] = bundle.sections[0]["text"].replace("Total revenue", "Missing label")
    with pytest.raises(ValueError, match="table context"):
        build_report_evidence(bundle.sections, bundle.metadata)


def test_discovery_exact_form_accession(monkeypatch):
    recent = dict(form=["10-Q", "10-K", "10-Q"],
                  accessionNumber=["0001193125-26-999999", "0001193125-26-323660", REPORT["accession"]],
                  primaryDocument=["new.htm", "annual.htm", REPORT["document"]],
                  filingDate=["2027-01-01", "2026-07-29", "2026-10-28"],
                  reportDate=["2026-12-31", "2026-06-30", "2026-09-30"])
    monkeypatch.setattr(filings, "fetch", lambda *a: json.dumps({"filings": {"recent": recent}}).encode())
    assert filings.discover_filing(789019, "test", "10-Q", REPORT["accession"])["document"] == REPORT["document"]
    assert filings.discover_latest_10k(789019, "test")["form"] == "10-K"
    with pytest.raises(ValueError, match="No recent"):
        filings.discover_filing(789019, "test", "10-K", REPORT["accession"])


def test_parquet_chunks_and_accession_isolation(bundle, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chunk_filings, "SECTIONS_DIR", Path("data/processed/filings"))
    store_filings.save_sections("MSFT", bundle.sections, Path("data/processed/filings"))
    annual = [{**s, "form": "10-K", "accession": "0001193125-26-323660", "item": "7",
               "text": "Annual revenue risk disclosure. " * 30} for s in bundle.sections[:1]]
    store_filings.save_sections("MSFT", annual, Path("data/processed/filings"))
    path, count = chunk_filings.process_ticker("MSFT")
    assert pq.read_table(path).num_rows == count
    results = search_module.search_filings("revenue", ticker="MSFT", limit=100, accession=REPORT["accession"])
    assert results and {r["accession"] for r in results} == {REPORT["accession"]}
    assert all(r["accession"] == "0001193125-26-323660" for r in search_module.search_filings("revenue"))
    assert search_module.search_filings("revenue", accession="absent") == []


def mock_client(report):
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=json.dumps(report), id="mock-response", usage=None)
    return client


def test_generation_inputs_exclude_oracle(bundle):
    client = mock_client(bundle.report)
    output, meta = generate_report(bundle.evidence, client=client)
    sent = client.responses.create.call_args.kwargs
    payload = json.loads(sent["input"])
    assert set(payload) == {"report", "requested_metrics", "interpretation_topics", "evidence"}
    assert all(set(m) == {"id", "label", "unit", "gaap_status"} for m in payload["requested_metrics"])
    assert "ground_truth" not in sent["input"] and "conclusion" not in sent["input"]
    assert output == bundle.report and meta["token_usage"] is None
    assert "92279" in render_report(output, bundle.evidence)
    assert "pending" not in json.dumps(output)  # review belongs exclusively to evaluation


@pytest.mark.parametrize("failure", ["incomplete", "empty", "invalid_json", "nonobject"])
def test_generation_failure(bundle, failure):
    client = mock_client(bundle.report)
    response = client.responses.create.return_value
    if failure == "incomplete": response.status = "incomplete"
    if failure == "empty": response.output_text = ""
    if failure == "invalid_json": response.output_text = "{"
    if failure == "nonobject": response.output_text = "[]"
    with pytest.raises((RuntimeError, ValueError)):
        generate_report(bundle.evidence, client=client)


def test_generation_refuses_wrong_filing(bundle):
    bundle.evidence[0]["accession"] = "wrong"
    client = Mock()
    with pytest.raises(ValueError): generate_report(bundle.evidence, client=client)
    client.responses.create.assert_not_called()


def test_evaluation_exact_numbers_and_pending_reviews(bundle):
    result = evaluate(bundle)
    assert result["financial_values"] == {"passed": 12, "total": 12}
    assert result["yoy_changes"] == {"passed": 6, "total": 6}
    assert result["table_evidence_support"] == {"passed": 6, "total": 6}
    assert result["automatic_pass"] and not result["overall_pass"]
    assert all(r["status"] == "pending_manual_review" for r in result["manual_reviews"])


@pytest.mark.parametrize("metric_index,period", [(i, p) for i in range(6) for p in ("current", "prior")])
def test_every_incorrect_value_detected(bundle, metric_index, period):
    bundle.report["metrics"][metric_index][period] = "4.91"
    result = evaluate(bundle)
    assert result["financial_values"]["passed"] == 11
    assert not result["automatic_pass"] and result["table_evidence_support"]["passed"] < 6


@pytest.mark.parametrize("corruption", ["yoy", "unit", "gaap_status", "period", "accession", "duplicate"])
def test_metadata_and_growth_failures(bundle, corruption):
    if corruption == "yoy": bundle.report["metrics"][0]["yoy_percent"] = "19.0"
    elif corruption in {"unit", "gaap_status"}: bundle.report["metrics"][0][corruption] = "wrong"
    elif corruption == "period": bundle.report["report"]["prior_start"] = "2024-07-01"
    elif corruption == "accession": bundle.report["report"]["accession"] = "wrong"
    else: bundle.report["metrics"].append(copy.deepcopy(bundle.report["metrics"][0]))
    assert not evaluate(bundle)["automatic_pass"]


@pytest.mark.parametrize("corruption", ["missing", "wrong_accession", "wrong_url", "wrong_hash", "wrong_text_hash", "unknown_id", "wrong_quote"])
def test_evidence_failures(bundle, corruption):
    if corruption == "missing": bundle.evidence.clear()
    elif corruption == "wrong_accession": bundle.evidence[0]["accession"] = "wrong"
    elif corruption == "wrong_url": bundle.evidence[0]["source_url"] = "https://example.com/other"
    elif corruption == "wrong_hash": bundle.evidence[0]["source_sha256"] = "0" * 64
    elif corruption == "wrong_text_hash": bundle.evidence[0]["text"] += "tampered"
    elif corruption == "unknown_id": bundle.report["metrics"][0]["citations"][0]["evidence_id"] = "unknown"
    else: bundle.report["metrics"][0]["citations"][0]["quote"] = "A fabricated quotation not in the source."
    assert not evaluate(bundle)["automatic_pass"]


def test_valid_reference_can_lack_claim_support(bundle):
    e = bundle.evidence[0]
    bundle.report["metrics"][0]["citations"] = [{"evidence_id": e["evidence_id"],
                                                "quote": "Refer to accompanying notes."}]
    result = evaluate(bundle)
    assert result["citation_integrity_pass"] and result["quote_membership_pass"]
    assert result["table_evidence_support"]["passed"] == 5
    assert not result["automatic_pass"]


def test_grouped_numbers_and_partial_table_delimiters(bundle):
    for m in bundle.report["metrics"]:
        for period in ("current", "prior"):
            if m["unit"] == "USD millions":
                m[period] = format(int(m[period]), ",")
        m["citations"][0]["quote"] = m["citations"][0]["quote"].strip("| \n")
    result = evaluate(bundle)
    assert result["financial_values"]["passed"] == 12
    assert result["table_evidence_support"]["passed"] == 6
    assert result["automatic_pass"]


@pytest.mark.parametrize("value", ["92,27,9", "9,2279", "NaN", "Infinity", "92 279", "9.2279e4", True, 92279])
def test_invalid_number_display_rejected(bundle, value):
    bundle.report["metrics"][0]["current"] = value
    assert evaluate(bundle)["financial_values"]["passed"] == 11


def test_wrong_semantic_note_does_not_automatically_pass(bundle):
    bundle.report["notes"][0]["text"] = "Adjusted measures are GAAP."
    result = evaluate(bundle)
    assert result["citation_integrity_pass"] and not result["overall_pass"]


def test_manual_review_requires_attribution_and_evidence(bundle):
    assert not evaluate(bundle, reviews={nid: {"status": "pass"} for nid in NOTE_IDS})["overall_pass"]
    reviews = {n["id"]: {"status": "pass", "reviewer": "Test reviewer", "rationale": "Controlled test decision",
                           "evidence_ids": [n["citations"][0]["evidence_id"]]} for n in bundle.report["notes"]}
    assert evaluate(bundle, reviews=reviews)["overall_pass"]
    reviews[NOTE_IDS[0]]["status"] = "fail"
    assert not evaluate(bundle, reviews=reviews)["overall_pass"]


def test_mocked_end_to_end_saved_run(bundle, tmp_path, monkeypatch):
    from evals import run_report
    monkeypatch.setattr(run_report, "save_sections", lambda ticker, records: store_filings.save_sections(ticker, records, tmp_path / "sections"))
    monkeypatch.setattr(run_report, "process_ticker", lambda ticker: None)
    client = mock_client(bundle.report)
    run_dir, result = run_report.run_baseline(snapshot_path=bundle.snapshot, client=client, reports_dir=tmp_path / "reports")
    assert result["automatic_pass"] and not result["overall_pass"]
    assert {"generated.json", "summary.md", "evidence.json", "source.json", "generation.json",
            "evaluation.json", "run.json", "instructions.txt", "sections.json"} <= {p.name for p in run_dir.iterdir()}
    assert run_report.reevaluate(run_dir)["financial_values"]["passed"] == 12
    assert client.responses.create.call_count == 1
    for path in run_dir.iterdir():
        assert "OPENAI_API_KEY" not in path.read_text(encoding="utf-8")
    assert run_report.main(["--evaluate-run", str(run_dir)]) == 2
    evidence_path = run_dir / "evidence.json"
    saved = json.loads(evidence_path.read_text())
    saved[0]["start_char"] += 1
    evidence_path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="section spans"):
        run_report.reevaluate(run_dir)


def test_failed_generation_saves_sanitized_artifacts(bundle, tmp_path, monkeypatch):
    from evals import run_report
    monkeypatch.setattr(run_report, "save_sections", lambda *a: None)
    monkeypatch.setattr(run_report, "process_ticker", lambda *a: None)
    client = Mock()
    client.responses.create.side_effect = RuntimeError("SECRET-MUST-NOT-BE-PERSISTED")
    root = tmp_path / "failed-runs"
    with pytest.raises(RuntimeError, match="incomplete"):
        run_report.run_baseline(snapshot_path=bundle.snapshot, client=client, reports_dir=root)
    run = next(root.iterdir())
    manifest = json.loads((run / "run.json").read_text())
    assert manifest["status"] == "incomplete" and manifest["error_type"] == "RuntimeError"
    assert not (run / "generated.json").exists()
    assert all("SECRET-MUST-NOT-BE-PERSISTED" not in p.read_text(encoding="utf-8") for p in run.iterdir())


def test_real_pinned_filing_evidence_if_cached():
    if not list((parse_filings.RAW_DIR / "MSFT" / REPORT["accession"]).glob("*.html")):
        pytest.skip("Pinned 10-Q not cached; no network calls in tests")
    sections = store_filings.prepare_sections("MSFT", form="10-Q", accession=REPORT["accession"])
    _, meta = parse_filings.load_latest_snapshot("MSFT", form="10-Q", accession=REPORT["accession"])
    evidence = build_report_evidence(sections, meta)
    from src.evaluation.report_evaluation import _source_row
    from decimal import Decimal
    for m in load_dataset()["metrics"]:
        supported = [_source_row(e, m["id"]) for e in evidence]
        assert any(row and row[1] == [Decimal(m[p]["value"]) for p in ("current", "prior")] for row in supported)

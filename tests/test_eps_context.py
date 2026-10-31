"""Saved second CAT response: bounded comparative EPS context, unchanged prose."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_cat_report import cat_case, PROFILE
from src.ai import report_assembly as assembly
from src.analytics.narrative_money import validate_monetary_narrative
from src.evaluation.report_evaluation import evaluate_report

SECOND = Path('evals/reports/m005/fresh-live/20261031T135327Z_98c78688')
FIXTURE = Path('tests/fixtures/cat_m005_second_notes.json')


def source(case):
    return [e['text'] for e in case.evidence if e['label']=='management_summary']


def test_exact_second_response_and_both_eps_clauses(cat_case):
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    text=raw['notes'][0]['text']
    result=validate_monetary_narrative(text,source(cat_case))
    assert result['automatic_pass'],result
    assert result['validation_version']=='cat-narrative-money-v2'
    assert [c['dimension'] for c in result['claims']]==[
        'USD/share','USD/share','USD/share','USD/share','USD','USD/share','USD','USD/share']
    assert [(c['text'],c['canonical_value']) for c in result['claims'] if c['dimension']=='USD']==[
        ('$41','41000000'),('$33','33000000')]
    for clause in text.split('. '):
        assert validate_monetary_narrative(clause,source(cat_case))['automatic_pass']
    # The compact source excerpt has different hashes, hence different IDs only.
    for note in raw['notes']:
        note['span_ids']=[s['span_id'] for s in cat_case.prepared['spans'] if s['claim_id']==note['id']]
    before=copy.deepcopy(raw)
    report=assembly.assemble(raw,cat_case.evidence,PROFILE)
    evaluated=evaluate_report(report,cat_case.evidence,cat_case.gt,
        source_sha256=cat_case.source['sha256'],profile=PROFILE)
    assert raw==before and [n['text'] for n in report['notes']]==[n['text'] for n in raw['notes']]
    assert evaluated['automatic_pass'] and not evaluated['overall_pass']
    assert evaluated['evaluation_version']=='m005-eval-v3'
    assert evaluated['narrative_monetary_units']['automatic_pass']


@pytest.mark.parametrize('comparison', [
    'in the three months ended March 31, 2026 and',
    'for 2026 and',
    'in the quarter ended March 31, 2026 versus',
    'during the three months ended March 31, 2026 compared with',
    'for the quarter ended March 31, 2026 compared to',
    'in March 31, 2026 against',
    'for the first quarter of 2026 and',
    'in Q1 2026 versus',
    'for 2026 compared with',
    'in the three months ended March 31, 2026 vs.',
])
def test_long_comparisons_preserve_only_eps(cat_case,comparison):
    result=validate_monetary_narrative(f'GAAP diluted EPS was $5.47 {comparison} $4.20 in 2025.',source(cat_case))
    assert result['automatic_pass'],result
    assert [c['dimension'] for c in result['claims']]==['USD/share','USD/share']


@pytest.mark.parametrize('text', [
    'EPS was $5.47 for 2026 and costs were $4.20 for 2025.',
    'EPS was $5.47 for 2026 and restructuring costs of $41 were disclosed.',
    'EPS was $5.47 for 2026 and $41 for 2025.',
    'EPS was $5.47 for 2026 and $4.21 for 2025.',
    'Costs were $41 in the three months ended March 31, 2026 and $33 in 2025.',
    'EPS was $5.47 in the three months ended March 31, 2026. Costs were $33.',
    'EPS was $5.47 in the three months ended March 31, 2026; $4.20 was disclosed.',
    'EPS was $5.47 (restructuring cost $41) for 2026 and $4.20 for 2025.',
    'EPS was $5.47 for 2026 and revenue of $4.20 was disclosed.',
    'EPS was $5.47 for 2026 and $4.20 million in 2025.',
    'EPS was $5.47 for 2026 and $41 million per share in 2025.',
    'EPS was $5.48 for 2026 and $4.20 for 2025.',
    'EPS was $5.47 for 2026 and management separately described profit as $4.20.',
    'Costs were $41 and $33 in 2025, while EPS was $4.20.',
])
def test_no_leakage_missing_units_or_unsupported_eps(cat_case,text):
    assert not validate_monetary_narrative(text,source(cat_case))['automatic_pass']


def test_mixed_paragraph_keeps_aggregate_and_share_dimensions(cat_case):
    text=('EPS was $5.47 in the three months ended March 31, 2026 and $4.20 in 2025. '
          'Adjusted EPS was $5.54 for 2026 and $4.25 for 2025. '
          'Restructuring costs were $41 million ($0.07 per share) and $33 million ($0.05 per share).')
    assert validate_monetary_narrative(text,source(cat_case))['automatic_pass']
    missing=text.replace('$41 million','$41').replace('$33 million','$33')
    result=validate_monetary_narrative(missing,source(cat_case))
    assert not result['automatic_pass']
    assert [c['text'] for c in result['errors']]==['$41','$33']
    assert not validate_monetary_narrative(text,[])['automatic_pass']


def test_shared_eps_requires_preceding_source_supported_claim(cat_case):
    result=validate_monetary_narrative('EPS was $5.48 for 2026 and $4.20 for 2025.',source(cat_case))
    assert not result['automatic_pass']
    assert result['claims'][1]['dimension']=='USD'


def test_real_second_response_replays_without_any_input_changes():
    if not SECOND.exists(): pytest.skip('Private run unavailable; byte-exact text fixture still tested')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SECOND.iterdir() if p.is_file()}
    read=lambda name:json.loads((SECOND/name).read_text(encoding='utf-8'))
    assert FIXTURE.read_bytes()==(SECOND/'raw_llm.json').read_bytes()
    report=assembly.assemble(read('raw_llm.json'),read('evidence.json'),PROFILE,read('assembly_inputs.json'))
    from src.evaluation.report_ground_truth import load_report_dataset
    result=evaluate_report(report,read('evidence.json'),load_report_dataset(PROFILE),
        source_sha256=read('source.json')['sha256'],profile=PROFILE)
    assert result['automatic_pass'] and not result['overall_pass']
    assert not (SECOND/'generated.json').exists()
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SECOND.iterdir() if p.is_file()}

"""Exact legacy punctuation and isolation of the JPM presentation path."""
import json
from pathlib import Path

import pytest
from test_report_profiles import case as msft_case
from test_cat_report import cat_case
from test_jpm_ai import case as jpm_case
from src.ai import report_assembly as assembly
from src.analytics import investor_report as ir

EXPECTED_LABELS = {
    'income_statement': 'Income statements \u00b7 Part I, Item 1',
    'segment_table': 'Segment disclosures \u00b7 Part I, Item 1',
    'segment_basis': 'Segment reporting basis \u00b7 Part I, Item 1',
    'recast_disclosure': 'Segment recast disclosure \u00b7 Part I, Item 1',
    'management_summary': 'Management discussion \u00b7 Part I, Item 2',
}
REVIEWED_STATUS = ('**Automated draft \u00b7 M004 presentation review pending.** '
                   'M003 automatic checks and qualitative reviews passed.')
PENDING_STATUS = ('**Automated draft \u00b7 Semantic and M004 presentation review pending.** '
                  'Automatic checks passed; human approval is required.')
# Both the observed double-encoded separator and the intermediate corruption.
MOJIBAKE = ('\u00c3\u201a\u00c2\u00b7', '\u00c2\u00b7')


@pytest.mark.parametrize('key,expected', list(EXPECTED_LABELS.items()))
def test_legacy_source_labels_are_exact(key, expected):
    assert ir.SOURCE_LABELS[key] == expected
    assert all(bad not in ir.SOURCE_LABELS[key] for bad in MOJIBAKE)


def view_for(c, profile):
    return ir.build_presentation({'config':assembly.get_profile(profile), 'report':c.report,
        'evidence':c.evidence,'registry':assembly.prepare(c.evidence,profile),
        'evaluation':{'automatic_pass':True,'overall_pass':False}})


def assert_exact_legacy_text(view, status):
    output=ir.render_main(view)
    meta=view['report'];company=view.get('company','Microsoft')
    assert output.splitlines()[0] == f"# {company} ({meta['ticker']}) \u00b7 {meta['fiscal_period']}"
    assert status in output
    for bad in MOJIBAKE:
        assert bad not in output
    for source in view['sources'].values():
        assert source['label'] in EXPECTED_LABELS.values()
        assert source['label'] in output
    return output


def test_msft_titles_status_and_source_labels(msft_case):
    view=view_for(msft_case,msft_case.profile)
    assert_exact_legacy_text(view,REVIEWED_STATUS)


@pytest.mark.parametrize('reviewed',[False,True])
def test_cat_titles_status_and_source_labels(cat_case,reviewed):
    view=view_for(cat_case,'cat_2026_q1');view['m003_overall_pass']=reviewed
    assert_exact_legacy_text(view,REVIEWED_STATUS if reviewed else PENDING_STATUS)


def test_reference_labels_use_original_middle_dot_boundary():
    view={'claims':{'claim':{'citations':[{'reference':'S1'}]}},
          'sources':{'S1':{'label':EXPECTED_LABELS['income_statement']}}}
    assert ir.references(view,['claim'])=='[Income statements][S1]'


def test_jpm_presentation_is_independent_of_legacy_encoding(jpm_case,monkeypatch):
    c=jpm_case;report=assembly.assemble(c.raw,c.evidence,'jpm_2026_q2')
    view=ir.build_banking_presentation(report,c.raw,c.extraction,c.payload,c.metadata)
    before=(ir.render_banking_main(report,view),ir.render_banking_details(report,view))
    monkeypatch.setattr(ir,'SOURCE_LABELS',{k:v.replace('\u00b7',MOJIBAKE[0]) for k,v in EXPECTED_LABELS.items()})
    def forbidden(*args):raise AssertionError('JPM must not use the legacy main renderer')
    monkeypatch.setattr(ir,'render_main',forbidden)
    assert (ir.render_banking_main(report,view),ir.render_banking_details(report,view))==before
    assert before[0].splitlines()[0]=='# JPMorgan Chase & Co. (JPM) - FY2026 Q2'
    assert all(bad not in text for text in before for bad in MOJIBAKE)


def test_saved_jpm_presentation_remains_byte_exact(jpm_case):
    saved=Path('evals/reports/m006/final-presentations/step5_20261031T174931Z_63f650d6')
    if (saved/'generated.json').exists():
        read=lambda name:json.loads((saved/name).read_text(encoding='utf-8'))
        report,view=read('generated.json'),read('presentation.json')
        assert ir.render_banking_main(report,view).encode('utf-8')==(saved/'report.md').read_bytes()
        assert ir.render_banking_details(report,view).encode('utf-8')==(saved/'supporting_detail.md').read_bytes()
    else:
        # Portable synthetic coverage when private audit artifacts are absent.
        c=jpm_case;report=assembly.assemble(c.raw,c.evidence,'jpm_2026_q2')
        view=ir.build_banking_presentation(report,c.raw,c.extraction,c.payload,c.metadata)
        assert ir.render_banking_main(report,view).splitlines()[0]=='# JPMorgan Chase & Co. (JPM) - FY2026 Q2'

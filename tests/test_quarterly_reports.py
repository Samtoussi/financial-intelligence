"""Synthetic saved-artifact fixtures; never used as application fallback data."""
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from src.ui import quarterly_reports as q


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def refresh_jpm_manifest(root):
    base=root/q.CATALOG['jpm_2026_q2']['directory']
    write_json(base/'artifact_hashes.json',{p.name:digest(p.read_bytes()) for p in base.iterdir()
        if p.is_file() and p.name!='artifact_hashes.json'})


def refresh_msft_manifest(root):
    config=q.CATALOG['msft_fy2026_q1'];base=root/config['directory'];source=root/config['source_run']
    (base/'m003_gate.json').write_bytes((source/'evaluation.json').read_bytes())
    write_json(base/'input_manifest.json',{'renderer_version':'m004-a-v2','profile':'msft_fy2026_q1',
        'input_directory':str(config['source_run']),
        'input_sha256':{p.name:digest(p.read_bytes()) for p in source.iterdir() if p.is_file()}})


@pytest.fixture
def artifacts(tmp_path,monkeypatch):
    monkeypatch.setattr(q,'ROOT',tmp_path)
    # These fixtures exercise the explicit private route, never a public fallback.
    render = q.render_quarterly_reports
    monkeypatch.setattr(q,'render_quarterly_reports',lambda **kwargs: render(public=False))
    for key,config in q.CATALOG.items():
        base=tmp_path/config['directory'];base.mkdir(parents=True)
        ticker=config['identity']['ticker']
        (base/'report.md').write_text(f'# Synthetic {ticker} report \u00b7 {config["identity"]["fiscal_period"]}\n\n'
            'Quarterly disclosure. [SEC](https://www.sec.gov/)\n\n[Details](supporting_detail.md).\n',encoding='utf-8')
        (base/'supporting_detail.md').write_text(f'# Synthetic {ticker} supporting detail\n\nSource \u2014 disclosure.\n',encoding='utf-8')
        write_json(base/'presentation.json',{'version':config['presentation_version'],'report':config['identity']})
        hashes={n:digest((base/n).read_bytes()) for n in ['report.md','supporting_detail.md']}
        write_json(base/'review_template.json',{'status':'pending_manual_review',
            'report_sha256':hashes['report.md'],'supporting_detail_sha256':hashes['supporting_detail.md']})
        write_json(base/'presentation_evaluation.json',{'evaluation_version':
            {'CAT':'m005-presentation-eval-v1','JPM':'m006-ai-presentation-v1','MSFT':'m004-a-eval-v2'}[ticker],
            'automatic_pass':True,'overall_pass':False,'failures':[],
            'review_status':'pending_manual_review'})
        if ticker=='CAT':
            gate={'evaluation_version':'m005-eval-v3','automatic_pass':True,'overall_pass':False,'failures':[]}
            write_json(base/'m003_gate.json',gate)
            write_json(base/'input_manifest.json',{'profile':key,'input_sha256':{
                'evaluation.json':digest((base/'m003_gate.json').read_bytes())}})
            approval=tmp_path/q.CAT_APPROVAL
            write_json(approval/'oracle_review.json',{'status':'pass','reviewer':'Synthetic test reviewer'})
            write_json(approval/'presentation_review.json',{'status':'pass','reviewer':'Synthetic test reviewer',
                'report_sha256':hashes['report.md'],'supporting_detail_sha256':hashes['supporting_detail.md']})
            topics=['gaap_vs_non_gaap','segment_comparability','sales_volume_and_price']
            write_json(approval/'review.json',{k:{'status':'pass','reviewer':'Synthetic test reviewer'} for k in topics})
            write_json(approval/'reviewed_evaluation.json',{**gate,'overall_pass':True})
            write_json(approval/'closure.json',{'presentation_directory':str(config['directory']),
                'artifact_sha256':{'report':hashes['report.md'],'supporting_detail':hashes['supporting_detail.md']},
                'approval_record_sha256':{n:digest((approval/n).read_bytes()) for n in
                    ['oracle_review.json','review.json','presentation_review.json','reviewed_evaluation.json']},
                'm005_overall_approved':True,'oracle_review_status':'pass','presentation_review_status':'pass',
                'semantic_review_statuses':dict.fromkeys(topics,'pass')})
        elif ticker=='MSFT':
            topics=['gaap_vs_non_gaap','segment_comparability','azure_growth_vs_cloud_margin']
            reviews={key:{'status':'pass','reviewer':'Synthetic reviewer','rationale':'Synthetic test evidence.',
                'evidence_ids':['synthetic-'+key]} for key in topics}
            source=tmp_path/config['source_run']
            gate={'evaluation_version':'m003-eval-v1','automatic_pass':True,'overall_pass':True,
                'failures':[],'metadata_pass':True,'citation_integrity_pass':True,'quote_membership_pass':True,
                'financial_values':{'passed':14,'total':14},'yoy_changes':{'passed':7,'total':7},
                'table_evidence_support':{'passed':7,'total':7},
                'manual_reviews':[{'id':key,**value} for key,value in reviews.items()]}
            write_json(source/'evaluation.json',gate)
            write_json(source/'review.json',reviews)
            write_json(source/'generated.json',{'report':config['identity']})
            write_json(source/'source.json',{'ticker':'MSFT','form':'10-Q','accession':config['identity']['accession'],
                'report_date':config['identity']['period_end']})
            write_json(source/'run.json',{'profile':key,'status':'completed_reviewed','overall_pass':True,
                'generation_mode':'m003-v2'})
            write_json(base/'presentation_evaluation.json',{'evaluation_version':'m004-a-eval-v2',
                'automatic_pass':True,'overall_pass':False,'failures':[],'m003_gate_pass':True,
                'manual_review_status':'pending_manual_review'})
            refresh_msft_manifest(tmp_path)
            (tmp_path/'evals/M004.md').write_text('# Synthetic documented presentation acceptance\n',encoding='utf-8')
        else:
            write_json(base/'evaluation.json',{'evaluation_version':'m006-ai-eval-v1','automatic_pass':True,
                'overall_pass':False,'financial':{'automatic_pass':True,'failures':[]},
                'narrative':{'automatic_pass':True,'failures':[]},'source_context_pass':True,'assembled_response_match':True})
            write_json(base/'review_context.json',{'user_stated_financial_and_semantic_review_passed':True})
            (tmp_path/'evals/M006.md').write_text('# Synthetic milestone approval documentation\n',encoding='utf-8')
            refresh_jpm_manifest(tmp_path)
    return tmp_path


@pytest.mark.parametrize('key',list(q.CATALOG))
def test_valid_saved_report_is_read_only_and_utf8(artifacts,key):
    before={p:digest(p.read_bytes()) for p in artifacts.rglob('*') if p.is_file()}
    result=q.load_report(key)
    base=artifacts/q.CATALOG[key]['directory']
    assert result['report']==(base/'report.md').read_bytes().decode('utf-8')
    assert '\u00b7' in result['report'] and '\u2014' in result['supporting_detail']
    assert result['automated_status']=='Passed'
    assert before=={p:digest(p.read_bytes()) for p in before}


def test_review_status_is_separate_from_automatic_pass(artifacts):
    cat=q.load_report('cat_2026_q1');jpm=q.load_report('jpm_2026_q2')
    assert cat['human_status']=='Approved (validated hash-bound review)'
    assert jpm['human_status']=='Pending in saved review records'
    assert 'Subsequent human approval' in jpm['human_note']
    assert 'Approved' not in jpm['human_status']


@pytest.mark.parametrize('key',list(q.CATALOG))
@pytest.mark.parametrize('name',['report.md','supporting_detail.md','presentation.json','presentation_evaluation.json','review_template.json'])
def test_missing_required_artifact_has_no_fallback(artifacts,key,name):
    (artifacts/q.CATALOG[key]['directory']/name).unlink()
    with pytest.raises(q.ReportUnavailable):q.load_report(key)


@pytest.mark.parametrize('key',list(q.CATALOG))
@pytest.mark.parametrize('field,value',[('ticker','WRONG'),('fiscal_period','FY2025 Q2'),('accession','wrong'),('date','2025-06-30')])
def test_identity_and_period_fail_closed(artifacts,key,field,value):
    base=artifacts/q.CATALOG[key]['directory'];obj=read_json(base/'presentation.json')
    field=('report_date' if key.startswith('jpm') else 'period_end') if field=='date' else field
    obj['report'][field]=value;write_json(base/'presentation.json',obj)
    with pytest.raises(q.ReportUnavailable,match='identity or reporting period'):q.load_report(key)


@pytest.mark.parametrize('key',list(q.CATALOG))
@pytest.mark.parametrize('name',['report.md','supporting_detail.md'])
def test_content_hash_mismatch_blocks_report(artifacts,key,name):
    p=artifacts/q.CATALOG[key]['directory']/name;p.write_text('Changed content',encoding='utf-8')
    with pytest.raises(q.ReportUnavailable,match='hash'):q.load_report(key)


@pytest.mark.parametrize('content',['{','[]','{"version":1,"version":2}'])
def test_malformed_metadata_is_unavailable(artifacts,content):
    p=artifacts/q.CATALOG['cat_2026_q1']['directory']/'presentation.json';p.write_text(content,encoding='utf-8')
    with pytest.raises(q.ReportUnavailable):q.load_report('cat_2026_q1')


@pytest.mark.parametrize('key',list(q.CATALOG))
def test_failed_presentation_evaluation_is_unavailable(artifacts,key):
    base=artifacts/q.CATALOG[key]['directory'];obj=read_json(base/'presentation_evaluation.json')
    obj['automatic_pass']=False;write_json(base/'presentation_evaluation.json',obj)
    with pytest.raises(q.ReportUnavailable,match='did not pass'):q.load_report(key)


@pytest.mark.parametrize('field',['financial','narrative','source_context_pass','assembled_response_match'])
def test_jpm_failed_underlying_evaluation_cannot_be_hidden(artifacts,field):
    base=artifacts/q.CATALOG['jpm_2026_q2']['directory'];obj=read_json(base/'evaluation.json')
    if field in ['financial','narrative']:obj[field]['automatic_pass']=False
    else:obj[field]=False
    write_json(base/'evaluation.json',obj);refresh_jpm_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='did not pass'):q.load_report('jpm_2026_q2')


def test_cat_failed_gate_is_unavailable(artifacts):
    base=artifacts/q.CATALOG['cat_2026_q1']['directory'];obj=read_json(base/'m003_gate.json')
    obj['automatic_pass']=False;write_json(base/'m003_gate.json',obj)
    write_json(base/'input_manifest.json',{'profile':'cat_2026_q1','input_sha256':{
        'evaluation.json':digest((base/'m003_gate.json').read_bytes())}})
    with pytest.raises(q.ReportUnavailable,match='did not pass'):q.load_report('cat_2026_q1')


@pytest.mark.parametrize('corruption',['missing','wrong_hash','wrong_directory','changed_review','not_approved'])
def test_cat_human_approval_requires_matching_evidence(artifacts,corruption):
    approval=artifacts/q.CAT_APPROVAL;obj=read_json(approval/'closure.json')
    if corruption=='missing':(approval/'presentation_review.json').unlink()
    elif corruption=='wrong_hash':obj['artifact_sha256']['report']='0'*64
    elif corruption=='wrong_directory':obj['presentation_directory']='another/report'
    elif corruption=='changed_review':write_json(approval/'review.json',{})
    else:obj['m005_overall_approved']=False
    write_json(approval/'closure.json',obj)
    with pytest.raises(q.ReportUnavailable):q.load_report('cat_2026_q1')


def test_jpm_cannot_promote_saved_pending_status(artifacts):
    base=artifacts/q.CATALOG['jpm_2026_q2']['directory'];obj=read_json(base/'review_template.json')
    obj['status']='pass';write_json(base/'review_template.json',obj);refresh_jpm_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='review status'):q.load_report('jpm_2026_q2')


def test_unknown_report_id_cannot_select_another_directory(artifacts):
    with pytest.raises(q.ReportUnavailable):q.load_report('../m005/live')


def test_only_known_relative_detail_links_are_changed():
    original='[Details](supporting_detail.md) [SEC](https://www.sec.gov/)\n`supporting_detail.md`'
    result=q.report_markdown(original)
    assert result=='[Details](#supporting-detail) [SEC](https://www.sec.gov/)\n`supporting_detail.md`'


def test_report_route_avoids_database_ai_and_generation(artifacts,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    def forbidden(*args,**kwargs):raise AssertionError('Report route must only read saved artifacts')
    targets=['duckdb.connect','src.analytics.financials.get_financial_history','openai.OpenAI',
        'src.ai.analyst.OpenAI','src.ai.report_assembly.generate','src.ai.report_assembly.assemble',
        'src.ai.report_generator.generate_report','src.analytics.investor_report.write_presentation']
    with ExitStack() as stack:
        for target in targets:stack.enter_context(patch(target,side_effect=forbidden))
        monkeypatch.setenv('OPENAI_API_KEY','')
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
        app.session_state['main_view']='Quarterly Reports';app.run()
        assert not app.exception and not app.error
        assert 'Synthetic CAT report' in '\n'.join(m.value for m in app.markdown)
        assert any('Human review: Approved' in item.value for item in app.success)
        assert any('[Details](#supporting-detail)' in m.value for m in app.markdown)
        app.selectbox[0].select('jpm_2026_q2').run()
        assert not app.exception and not app.error
        assert any('Pending in saved review records' in item.value for item in app.info)
        assert not any('Human review: Approved' in item.value for item in app.success)
        assert any('M006 milestone documentation' in m.value for m in app.markdown)
        assert any('Source \u2014 disclosure.' in m.value for m in app.markdown)
        assert len(app.chat_input)==0


def test_report_route_displays_missing_artifacts_explicitly(tmp_path,monkeypatch):
    monkeypatch.setattr(q,'ROOT',tmp_path)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
    app.session_state['main_view']='Quarterly Reports';app.run()
    assert not app.exception and any('unavailable' in error.value for error in app.error)
    assert not app.success


def test_cat_gate_hash_provenance_must_match(artifacts):
    base=artifacts/q.CATALOG['cat_2026_q1']['directory']
    obj=read_json(base/'m003_gate.json');obj['extra']='changed'
    write_json(base/'m003_gate.json',obj)
    with pytest.raises(q.ReportUnavailable,match='provenance'):q.load_report('cat_2026_q1')


def test_jpm_changed_metadata_manifest_is_unavailable(artifacts):
    base=artifacts/q.CATALOG['jpm_2026_q2']['directory']
    obj=read_json(base/'presentation.json');obj['extra']='changed'
    write_json(base/'presentation.json',obj)
    with pytest.raises(q.ReportUnavailable,match='has changed'):q.load_report('jpm_2026_q2')


def test_cat_pending_approval_cannot_be_presented_as_approved(artifacts):
    approval=artifacts/q.CAT_APPROVAL
    obj=read_json(approval/'presentation_review.json');obj['status']='pending_manual_review'
    write_json(approval/'presentation_review.json',obj)
    closure=read_json(approval/'closure.json')
    closure['approval_record_sha256']['presentation_review.json']=digest((approval/'presentation_review.json').read_bytes())
    write_json(approval/'closure.json',closure)
    with pytest.raises(q.ReportUnavailable,match='incomplete'):q.load_report('cat_2026_q1')


def test_navigation_returns_to_existing_dashboard(artifacts):
    import streamlit as st
    st.cache_data.clear()
    rows=[dict(cik=789019,fiscal_year=2025,revenue_usd=110_000_000_000,
        yoy_growth_pct=None,is_comparable=False,period_start='2024-07-01',period_end='2025-06-30',
        source_concept='Synthetic test revenue',source_accession='0000789019-25-000100',
        source_filed_date='2025-07-30')]
    with patch('src.analytics.financials.get_financial_history',return_value=rows) as history:
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
        app.session_state['main_view']='Dashboard';app.run()
        assert not app.exception
        assert app.selectbox[0].label=='Company'
        count=history.call_count
        app.radio[0].set_value('Quarterly Reports').run()
        assert not app.exception and not app.error
        assert history.call_count==count
        assert app.selectbox[0].label=='Report'
        app.radio[0].set_value('Dashboard').run()
        assert not app.exception
        assert app.selectbox[0].label=='Company'
        assert app.dataframe[0].value['Fiscal year'].tolist()==['2025']


@pytest.mark.parametrize('name',['review_context.json','artifact_hashes.json'])
def test_missing_jpm_review_or_hash_evidence_is_unavailable(artifacts,name):
    (artifacts/q.CATALOG['jpm_2026_q2']['directory']/name).unlink()
    with pytest.raises(q.ReportUnavailable):q.load_report('jpm_2026_q2')

@pytest.mark.parametrize('amount',['$675 million','$58,022 million','$564 million','$111 million',
    '$2.5 billion','$2.4 billion','$149 million','$31,531 million','$7.70 per share','$ 62,889','$-41 million'])
def test_financial_dollars_are_literal_and_values_are_unchanged(amount):
    rendered=q.report_markdown('Disclosed amount: '+amount+'.')
    assert rendered=='Disclosed amount: '+amount.replace('$',r'\$')+'.'
    assert q.report_markdown(rendered)==rendered


def test_financial_tables_links_and_emphasis_are_preserved():
    original=('**FTE adjustments** increased revenue by $675 million to $58,022 million.\n\n'
              '| Measure | Amount | Source |\n|---|---:|---|\n'
              '| Revenue | $58,022 million | [SEC][S1] |\n\n'
              '[Details](supporting_detail.md)\n[S1]: https://www.sec.gov/filing?$675\n')
    rendered=q.report_markdown(original)
    assert '**FTE adjustments**' in rendered
    assert '| Revenue | \\$58,022 million | [SEC][S1] |' in rendered
    assert '|---|---:|---|' in rendered
    assert '[Details](#supporting-detail)' in rendered
    assert '[S1]: https://www.sec.gov/filing?$675' in rendered
    assert rendered.replace(r'\$','$').replace('](#supporting-detail)','](supporting_detail.md)')==original


@pytest.mark.parametrize('literal',[
    '`$675 million`',
    '``$675 million ` and $111 million``',
    '```text\n$675 million; $58,022 million\n[Original link](supporting_detail.md)\n```\n',
    '~~~text\n$675 million and $111 million\n~~~\n',
    '[SEC](https://www.sec.gov/filing?$675)',
    '[Local](file-$675.md)',
    'https://www.sec.gov/filing?$675',
    '$x^2$ remains a math expression.',
    r'Already escaped \$675 million.',
])
def test_literal_code_links_and_existing_formatting_are_not_rewritten(literal):
    assert q.report_markdown(literal)==literal


def test_code_evidence_is_preserved_while_surrounding_financial_prose_is_escaped():
    original='$675 million.\n```text\n$564 million\n```\nThen $111 million.'
    assert q.report_markdown(original)=='\\$675 million.\n```text\n$564 million\n```\nThen \\$111 million.'


def test_display_polish_layout_status_and_collapsed_full_evidence(artifacts,monkeypatch):
    original_load=q.load_report
    financial='FTE adjustments increased revenue by $675 million to $58,022 million.'
    evidence='\n```text\nExact source disclosure: $564 million and $111 million.\n```\n'
    def rich_report(key):
        saved=original_load(key)
        return {**saved,'report':saved['report']+'\n'+financial,
                'supporting_detail':saved['supporting_detail']+evidence}
    monkeypatch.setattr(q,'load_report',rich_report)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
    app.session_state['main_view']='Quarterly Reports';app.run()
    assert not app.exception and not app.error
    columns=[c for c in app.get('flex_container') if 'quarterly-reading-column' in c.proto.id]
    assert len(columns)==1 and columns[0].proto.width_config.pixel_width==1100
    assert app.radio[0].options==['Dashboard','Quarterly Reports']
    assert any(h.value=='Current review evidence' for h in app.subheader)
    captions='\n'.join(c.value for c in app.caption)
    assert 'original generation state' in captions and 'current review evidence above is authoritative' in captions
    assert app.expander[0].label=='Detailed source evidence'
    assert app.expander[0].proto.expanded is False
    assert any(q.report_markdown(financial) in m.value for m in app.markdown)
    expected=rich_report('cat_2026_q1')['supporting_detail']
    assert app.expander[0].markdown[0].value==q.report_markdown(expected).strip()
    assert evidence.rstrip() in app.expander[0].markdown[0].value
    assert not any('<style>' in m.value for m in app.markdown)
    app.selectbox[0].select('jpm_2026_q2').run()
    assert not app.exception
    assert any('Pending in saved review records' in info.value for info in app.info)
    assert not any('Human review: Approved' in success.value for success in app.success)
    assert any('A final hash-bound human approval record is not present' in c.value for c in app.caption)
    assert app.expander[0].proto.expanded is False


def test_msft_catalog_and_status_separation(artifacts):
    config=q.CATALOG['msft_fy2026_q1'];saved=q.load_report('msft_fy2026_q1')
    assert config['identity']['accession']=='0001193125-25-256321'
    assert config['identity']['period_start']=='2025-07-01'
    assert config['identity']['period_end']=='2025-09-30'
    assert 'FY2026 Q1' in saved['label'] and 'Jul-Sep 2025' in saved['label']
    assert saved['automated_status']=='Passed'
    assert saved['human_status']=='Semantic review passed; presentation acceptance documented'
    assert 'archived presentation record remains pending' in saved['human_note']
    assert 'no hash-bound final presentation approval' in saved['human_note']
    base=artifacts/config['directory']
    assert read_json(base/'presentation_evaluation.json')['overall_pass'] is False
    assert read_json(base/'review_template.json')['status']=='pending_manual_review'


@pytest.mark.parametrize('name',['m003_gate.json','input_manifest.json'])
def test_missing_msft_presentation_gate_or_manifest_is_unavailable(artifacts,name):
    (artifacts/q.CATALOG['msft_fy2026_q1']['directory']/name).unlink()
    with pytest.raises(q.ReportUnavailable):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('name',['evaluation.json','source.json','review.json','generated.json','run.json'])
def test_missing_msft_reviewed_source_is_unavailable(artifacts,name):
    (artifacts/q.CATALOG['msft_fy2026_q1']['source_run']/name).unlink()
    with pytest.raises(q.ReportUnavailable):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('field,value',[
    ('profile','msft_fy2027_q1'),('renderer_version','m004-a-v1'),
    ('input_directory','evals/reports/m003/another-run')])
def test_msft_manifest_cannot_select_other_profiles_or_runs(artifacts,field,value):
    base=artifacts/q.CATALOG['msft_fy2026_q1']['directory'];obj=read_json(base/'input_manifest.json')
    obj[field]=value;write_json(base/'input_manifest.json',obj)
    with pytest.raises(q.ReportUnavailable,match='different run or profile'):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('corruption',['source_hash','gate_hash','missing_hash','unsafe_name'])
def test_msft_manifest_lineage_is_enforced(artifacts,corruption):
    config=q.CATALOG['msft_fy2026_q1'];base=artifacts/config['directory'];source=artifacts/config['source_run']
    obj=read_json(base/'input_manifest.json')
    if corruption=='source_hash':
        data=read_json(source/'source.json');data['extra']='changed';write_json(source/'source.json',data)
    elif corruption=='gate_hash':
        data=read_json(base/'m003_gate.json');data['extra']='changed';write_json(base/'m003_gate.json',data)
    elif corruption=='missing_hash':obj['input_sha256'].pop('evaluation.json')
    else:obj['input_sha256']['../outside.json']='0'*64
    write_json(base/'input_manifest.json',obj)
    with pytest.raises(q.ReportUnavailable):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('field',['automatic_pass','overall_pass','metadata_pass','citation_integrity_pass','quote_membership_pass'])
def test_msft_financial_semantic_or_source_gate_cannot_fail(artifacts,field):
    source=artifacts/q.CATALOG['msft_fy2026_q1']['source_run'];obj=read_json(source/'evaluation.json')
    obj[field]=False;write_json(source/'evaluation.json',obj);refresh_msft_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='did not pass'):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('field',['financial_values','yoy_changes','table_evidence_support'])
def test_msft_incomplete_financial_counters_are_unavailable(artifacts,field):
    source=artifacts/q.CATALOG['msft_fy2026_q1']['source_run'];obj=read_json(source/'evaluation.json')
    obj[field]['passed']-=1;write_json(source/'evaluation.json',obj);refresh_msft_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='incomplete'):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('corruption',['failed','empty_reviewer','missing_topic','different_evidence'])
def test_msft_semantic_acceptance_needs_matching_passed_reviews(artifacts,corruption):
    source=artifacts/q.CATALOG['msft_fy2026_q1']['source_run'];obj=read_json(source/'review.json')
    first=next(iter(obj))
    if corruption=='failed':obj[first]['status']='fail'
    elif corruption=='empty_reviewer':obj[first]['reviewer']=''
    elif corruption=='missing_topic':obj.pop(first)
    else:obj[first]['evidence_ids']=['different-evidence']
    write_json(source/'review.json',obj);refresh_msft_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='semantic review'):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('name,field,value',[
    ('source.json','accession','0001193125-26-436133'),
    ('source.json','report_date','2026-09-30'),
    ('run.json','status','incomplete'),('run.json','generation_mode','legacy')])
def test_msft_source_identity_and_reviewed_run_are_required(artifacts,name,field,value):
    source=artifacts/q.CATALOG['msft_fy2026_q1']['source_run'];obj=read_json(source/name)
    obj[field]=value;write_json(source/name,obj);refresh_msft_manifest(artifacts)
    with pytest.raises(q.ReportUnavailable,match='identity, period or run state'):q.load_report('msft_fy2026_q1')


@pytest.mark.parametrize('corruption',['gate_false','presentation_promoted','template_promoted','malformed','missing_document'])
def test_msft_presentation_status_and_documentation_are_preserved(artifacts,corruption):
    base=artifacts/q.CATALOG['msft_fy2026_q1']['directory']
    obj=read_json(base/'presentation_evaluation.json')
    if corruption=='gate_false':obj['m003_gate_pass']=False
    elif corruption=='presentation_promoted':obj['overall_pass']=True
    elif corruption=='template_promoted':
        review=read_json(base/'review_template.json');review['status']='pass';write_json(base/'review_template.json',review)
    elif corruption=='malformed':
        (base/'input_manifest.json').write_text('[]',encoding='utf-8')
    else:(artifacts/'evals/M004.md').unlink()
    write_json(base/'presentation_evaluation.json',obj)
    with pytest.raises(q.ReportUnavailable):q.load_report('msft_fy2026_q1')


def test_msft_ui_has_three_review_stages_and_reuses_report_display(artifacts):
    def forbidden(*args,**kwargs):raise AssertionError('Saved report route must not invoke services')
    targets=['duckdb.connect','src.analytics.financials.get_financial_history','openai.OpenAI',
        'src.ai.analyst.OpenAI','src.ai.report_assembly.generate','src.ai.report_assembly.assemble',
        'src.ai.report_generator.generate_report','src.analytics.investor_report.write_presentation']
    with ExitStack() as stack:
        for target in targets:stack.enter_context(patch(target,side_effect=forbidden))
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
        app.session_state['main_view']='Quarterly Reports';app.run()
        app.selectbox[0].select('msft_fy2026_q1').run()
        assert not app.exception and not app.error
        assert any('Saved automated evaluation: Passed' in v.value for v in app.success)
        assert any('Semantic review: Passed (saved M003 gate)' in v.value for v in app.success)
        assert any('Human presentation acceptance: Documented in M004' in v.value for v in app.info)
        assert not any('Human review: Approved' in v.value for v in app.success)
        assert any('M004 presentation acceptance' in v.value for v in app.markdown)
        assert any('remains pending' in v.value for v in app.caption)
        assert any('Synthetic MSFT report' in v.value for v in app.markdown)
        assert any('[Details](#supporting-detail)' in v.value for v in app.markdown)
        assert app.expander[0].label=='Detailed source evidence' and not app.expander[0].proto.expanded
        assert len(app.chat_input)==0
        # Existing selections retain their original status policies.
        app.selectbox[0].select('cat_2026_q1').run()
        assert not app.exception and any('Human review: Approved' in v.value for v in app.success)
        app.selectbox[0].select('jpm_2026_q2').run()
        assert not app.exception and any('Pending in saved review records' in v.value for v in app.info)

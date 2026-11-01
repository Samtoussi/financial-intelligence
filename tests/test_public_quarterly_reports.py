"""Public snapshots work without private runtime inputs or online services."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from src.ui import public_quarterly_reports as public
from src.ui import quarterly_reports as private

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle(tmp_path):
    shutil.copytree(ROOT/public.BUNDLE,tmp_path/public.BUNDLE)
    return tmp_path


def rewrite(root, monkeypatch, key, mutate):
    base=root/public.BUNDLE
    path=base/key
    value=json.loads(path.read_text(encoding='utf-8'))
    mutate(value)
    path.write_text(json.dumps(value),encoding='utf-8')
    manifest=base/'manifest.json'
    if key!='manifest.json':
        value=json.loads(manifest.read_text(encoding='utf-8'))
        value['files'][key]=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value),encoding='utf-8')
    monkeypatch.setattr(public,'MANIFEST_SHA256',hashlib.sha256(manifest.read_bytes()).hexdigest())


@pytest.mark.parametrize('key',public.REPORT_IDS)
def test_public_valid_offline(bundle,monkeypatch,key):
    monkeypatch.setattr(private,'load_report',lambda *a,**k:pytest.fail('Private fallback'))
    result=public.load_public_report(key,root=bundle)
    assert result['verification']['identity']==private.CATALOG[key]['identity']
    assert public.SCOPE==result['scope']
    assert 'does not independently rerun' in result['scope']
    assert '| Metric' in result['supporting_detail']
    assert '```' not in result['supporting_detail']
    assert '\ufffd' not in result['report']
    assert '(#supporting-detail)' in private.report_markdown(result['report'])
    assert 'https://www.sec.gov/' in result['supporting_detail']
    assert result['verification']['presentation_acceptance']['publication_derivative_approval']=='separate_content_approval_record'
    assert result['verification']['presentation_acceptance']['applies_to']=='runtime_original_only'
    assert result['publication_content_approval']['rights_review']['legal_clearance'] is False
    if key!='cat_2026_q1':
        assert result['verification']['presentation_acceptance']['state']=='documented_acceptance'


@pytest.mark.parametrize('name',['manifest.json','NOTICE.md','publication_approval.json']+[k+'/'+n for k in public.REPORT_IDS for n in ('report.md','supporting_detail.md','verification.json')])
def test_missing_fails_closed(bundle,name):
    (bundle/public.BUNDLE/name).unlink()
    with pytest.raises(private.ReportUnavailable):public.load_public_report(public.REPORT_IDS[0],root=bundle)


@pytest.mark.parametrize('name',['manifest.json','NOTICE.md','publication_approval.json','msft_fy2026_q1/report.md','cat_2026_q1/supporting_detail.md','jpm_2026_q2/verification.json'])
def test_hash_mismatch(bundle,name):
    with (bundle/public.BUNDLE/name).open('ab') as f:f.write(b' ')
    with pytest.raises(private.ReportUnavailable):public.load_public_report(public.REPORT_IDS[0],root=bundle)


@pytest.mark.parametrize('key',public.REPORT_IDS)
@pytest.mark.parametrize('field',['ticker','fiscal_period','accession'])
def test_wrong_identity(bundle,monkeypatch,key,field):
    rewrite(bundle,monkeypatch,key+'/verification.json',lambda v:v['identity'].__setitem__(field,'wrong'))
    with pytest.raises(private.ReportUnavailable,match='company, period or accession'):public.load_public_report(key,root=bundle)


@pytest.mark.parametrize('mutation',[
    lambda v:v.__setitem__('format','unsupported'),
    lambda v:v.__setitem__('saved_evaluation',None),
    lambda v:v['saved_evaluation']['financial'].__setitem__('automatic_pass',False),
    lambda v:v['saved_evaluation']['presentation'].__setitem__('automatic_pass',False),
    lambda v:v['semantic_review'].__setitem__('state','approved'),
    lambda v:v['presentation_acceptance'].__setitem__('publication_derivative_approval','approved'),
    lambda v:v['sources'][0].__setitem__('url','https://example.com'),
    lambda v:v['derivation'].__setitem__('private_lineage','Source evaluation rerun'),
])
def test_unsupported_or_overstated_metadata(bundle,monkeypatch,mutation):
    key=public.REPORT_IDS[0]
    rewrite(bundle,monkeypatch,key+'/verification.json',mutation)
    with pytest.raises(private.ReportUnavailable):public.load_public_report(key,root=bundle)


@pytest.mark.parametrize('mutation',[
    lambda v:v.__setitem__('state','legal_authorization'),
    lambda v:v['files'].__setitem__('msft_fy2026_q1/report.md','0'*64),
    lambda v:v['files'].pop('cat_2026_q1/supporting_detail.md'),
    lambda v:v['files'].__setitem__('runtime_original/report.md','0'*64),
    lambda v:v['rights_review'].__setitem__('legal_clearance',True),
    lambda v:v['rights_review'].__setitem__('issuer_permission_obtained',True),
    lambda v:v['rights_review'].__setitem__('independent_evaluation_performed',True),
])
def test_content_approval_cannot_cover_other_versions_or_claim_rights(bundle,monkeypatch,mutation):
    rewrite(bundle,monkeypatch,'publication_approval.json',mutation)
    with pytest.raises(private.ReportUnavailable):public.load_public_report(public.REPORT_IDS[0],root=bundle)


def test_rehashed_report_edit_does_not_transfer_content_approval(bundle,monkeypatch):
    base=bundle/public.BUNDLE
    report=base/'msft_fy2026_q1/report.md'
    report.write_bytes(report.read_bytes()+b'\nEditorial change after approval.\n')
    rewrite(bundle,monkeypatch,'manifest.json',lambda v:v['files'].__setitem__(
        'msft_fy2026_q1/report.md',hashlib.sha256(report.read_bytes()).hexdigest()))
    with pytest.raises(private.ReportUnavailable,match='different report versions'):
        public.load_public_report(public.REPORT_IDS[0],root=bundle)


def test_traversal(bundle,monkeypatch):
    rewrite(bundle,monkeypatch,'manifest.json',lambda v:v['files'].__setitem__('../secret','0'*64))
    with pytest.raises(private.ReportUnavailable):public.load_public_report(public.REPORT_IDS[0],root=bundle)
    with pytest.raises(private.ReportUnavailable):public.load_public_report('../secret',root=bundle)


def test_malformed_json(bundle,monkeypatch):
    path=bundle/public.BUNDLE/'manifest.json'
    path.write_bytes(b'{')
    monkeypatch.setattr(public,'MANIFEST_SHA256',hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(private.ReportUnavailable):public.load_public_report(public.REPORT_IDS[0],root=bundle)


def test_clean_checkout_streamlit_without_private_backend(tmp_path):
    """Tracked files plus explicitly proposed publication files, no ignored artifacts."""
    tracked=subprocess.check_output(['git','-c','safe.directory='+str(ROOT).replace('\\','/'),'ls-files'],cwd=ROOT,text=True).splitlines()
    proposed=['app.py','src/ui/quarterly_reports.py','src/ui/public_quarterly_reports.py','.gitattributes']
    proposed += [str(p.relative_to(ROOT)) for p in (ROOT/public.BUNDLE).rglob('*') if p.is_file()]
    for name in set(tracked+proposed):
        source=ROOT/name
        if source.is_file():
            target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    assert not (tmp_path/'evals/reports').exists()
    assert not (tmp_path/'data').exists()
    script=r'''
import builtins, socket
from streamlit.testing.v1 import AppTest
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('duckdb','openai','src.ai','src.ingestion','src.analytics.financials')):
        raise AssertionError('Forbidden report-route backend import: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
def blocked(*args,**kwargs):raise AssertionError('Forbidden network call')
# Windows asyncio uses a loopback socketpair internally.
connect=socket.socket.connect
def offline_connect(sock,address):
    if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'):
        return connect(sock,address)
    return blocked(sock,address)
socket.socket.connect=offline_connect
socket.create_connection=blocked
socket.getaddrinfo=blocked
from src.ui import quarterly_reports as private
private.load_report=blocked
app=AppTest.from_file('app.py',default_timeout=20).run()
assert not app.exception and not app.error
assert app.radio[0].value=='Quarterly Reports'
for key in ('msft_fy2026_q1','cat_2026_q1','jpm_2026_q2'):
    app.selectbox[0].select(key).run()
    assert not app.exception and not app.error
    assert any('does not independently rerun' in x.value for x in app.info)
    assert any('not legal clearance' in x.value for x in app.warning)
    assert any('owner-approved for these exact public files' in x.value for x in app.success)
    assert app.expander[0].label=='Verified financial tables and SEC sources'
    assert any('original generation state' in x.value for x in app.caption)
print('Three public reports rendered without private artifacts, backend imports or network')
'''
    env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','SEC_USER_AGENT')}
    env['PYTHONPATH']=str(tmp_path);env['PYTHONDONTWRITEBYTECODE']='1'
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr

"""Explicit public snapshots: published-byte checks, not private-source replay."""
from pathlib import Path

import streamlit as st
from src.ui import quarterly_reports as local

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path('showcase/quarterly')
REPORT_IDS = ('msft_fy2026_q1','cat_2026_q1','jpm_2026_q2')
MANIFEST_SHA256 = '380f528ffbc85e4061b6ae91ef382b7bf522e0e173601a6eec93a9788a1d754c'
SCOPE = ('Verifies published-file integrity and reports saved evaluation outcomes; '
         'does not independently rerun the original source evaluation.')
SOURCES = {
    'msft_fy2026_q1':'https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/msft-20250930.htm',
    'cat_2026_q1':'https://www.sec.gov/Archives/edgar/data/18230/000001823026000021/cat-20260331.htm',
    'jpm_2026_q2':'https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/jpm-20260630.htm',
}
VERSIONS = {
    'msft_fy2026_q1':('m003-eval-v1','m004-a-eval-v2',14,7,7,'evals/M004.md'),
    'cat_2026_q1':('m005-eval-v3','m005-presentation-eval-v1',16,8,8,'evals/M005_FINAL_VERIFICATION.md'),
    'jpm_2026_q2':('m006-financial-eval-v1','m006-ai-presentation-v1',16,6,8,'evals/M006.md'),
}


def load_public_report(report_id, *, root=None):
    """No private fallback, source re-evaluation, database access or generation."""
    require = local._require
    require(report_id in REPORT_IDS,'Unknown public report.')
    root = Path(root) if root is not None else ROOT
    try:
        raw = local._read(root,BUNDLE/'manifest.json')
        require(local._digest(raw) == MANIFEST_SHA256,'Public bundle manifest hash does not match the release catalog.')
        manifest = local._json(raw)
        require(set(manifest) == {'format','scope','release_state','report_ids','files'}
            and manifest['format'] == 'fi-quarterly-publication-v1' and manifest['scope'] == SCOPE
            and manifest['release_state'] == 'content_approved_subject_to_rights_restrictions'
            and manifest['report_ids'] == list(REPORT_IDS),'Unsupported public publication metadata.')
        expected = {'NOTICE.md','publication_approval.json'} | {key+'/'+name for key in REPORT_IDS
            for name in ('report.md','supporting_detail.md','verification.json')}
        require(isinstance(manifest['files'],dict) and set(manifest['files']) == expected,
            'Public bundle file list is invalid or incomplete.')
        blobs = {}
        for name,digest in manifest['files'].items():
            data = local._read(root,BUNDLE/name)
            require(local._digest(data) == digest,'Published file hash does not match.')
            blobs[name] = data
        approval = local._json(blobs['publication_approval.json'])
        markdown = {key+'/'+name for key in REPORT_IDS for name in ('report.md','supporting_detail.md')}
        require(set(approval) == {'format','state','authority','owner_statement','scope','files',
                                 'publication_approach','rights_review'}
            and approval['format'] == 'fi-publication-content-approval-v1'
            and approval['state'] == 'owner_content_approved_subject_to_rights_restrictions'
            and isinstance(approval['files'],dict) and set(approval['files']) == markdown
            and all(approval['files'][name] == local._digest(blobs[name]) for name in markdown)
            and all(isinstance(approval[k],str) and approval[k].strip() for k in
                    ('authority','owner_statement','scope','publication_approach')),
            'Publication content approval is incomplete or belongs to different report versions.')
        rights = approval['rights_review']
        require(isinstance(rights,dict) and set(rights) == {'state','basis','limitation','condition',
                    'legal_clearance','issuer_permission_obtained','independent_evaluation_performed'}
            and rights['state'] == 'no_specific_restriction_identified_in_reviewed_material'
            and all(rights[k] is False for k in ('legal_clearance','issuer_permission_obtained',
                                               'independent_evaluation_performed'))
            and all(isinstance(rights[k],str) and rights[k].strip() for k in ('basis','limitation','condition')),
            'Publication content approval overstates evaluation or rights authorization.')
        value = local._json(blobs[report_id+'/verification.json'])
        require(set(value) == {'format','report_id','identity','sources','derivation','saved_evaluation',
            'semantic_review','presentation_acceptance'} and value['format'] == 'fi-public-verification-v1'
            and value['report_id'] == report_id,'Unsupported public verification metadata.')
        require(value['identity'] == local.CATALOG[report_id]['identity'],
            'Public company, period or accession does not match.')
        sources = value['sources']
        require(isinstance(sources,list) and bool(sources) and all(isinstance(s,dict)
            and set(s) == {'label','url'} and isinstance(s['label'],str) and s['label'].strip()
            and s['url'] == SOURCES[report_id] for s in sources),'Public SEC source identity is invalid.')
        fversion,pversion,*counts,document = VERSIONS[report_id]
        financial = value['saved_evaluation']['financial'];presentation = value['saved_evaluation']['presentation']
        require(set(value['saved_evaluation']) == {'financial','presentation'}
            and set(financial) == {'version','automatic_pass','counters','evidence_sha256'}
            and set(presentation) == {'version','automatic_pass','archived_overall_pass','evidence_sha256'}
            and financial['version'] == fversion and presentation['version'] == pversion
            and financial['automatic_pass'] is True and presentation['automatic_pass'] is True
            and presentation['archived_overall_pass'] is False,'Saved public evaluation status is invalid.')
        require(set(financial['counters']) == {'financial_values','yoy_changes','table_evidence_support'},
            'Saved financial counter fields are invalid.')
        for name,count in zip(('financial_values','yoy_changes','table_evidence_support'),counts):
            counter = financial['counters'][name]
            require(isinstance(counter,dict) and set(counter) == {'passed','total'}
                and type(counter['passed']) is int and type(counter['total']) is int
                and counter == {'passed':count,'total':count},'Saved financial counters are incomplete.')
        semantic = value['semantic_review'];acceptance = value['presentation_acceptance']
        require(set(semantic) == {'state','archived_state','documentation','evidence_sha256'}
            and semantic['state'] == ('documented_acceptance' if report_id=='jpm_2026_q2' else 'passed_saved_reviews')
            and semantic['archived_state'] == ('pass' if report_id=='msft_fy2026_q1' else 'pending_manual_review')
            and semantic['documentation'] == document,'Public semantic-review status is invalid.')
        require(set(acceptance) == {'state','archived_state','documentation','evidence_sha256','applies_to','publication_derivative_approval'}
            and acceptance['state'] == ('original_hash_bound_approval' if report_id=='cat_2026_q1' else 'documented_acceptance')
            and acceptance['archived_state'] == 'pending_manual_review' and acceptance['documentation'] == document
            and acceptance['applies_to'] == 'runtime_original_only'
            and acceptance['publication_derivative_approval'] == 'separate_content_approval_record',
            'Public presentation acceptance overstates the saved evidence.')
        derivation = value['derivation']
        require(set(derivation) == {'original_report_sha256','original_supporting_detail_sha256','changes','private_lineage'}
            and isinstance(derivation['changes'],list) and bool(derivation['changes'])
            and derivation['private_lineage'] == 'Validated during curation using the strict local loader; private inputs are not included or rechecked by the public loader.',
            'Public derivation scope is invalid.')
        import re
        for digest in [financial['evidence_sha256'],presentation['evidence_sha256'],semantic['evidence_sha256'],
                       acceptance['evidence_sha256'],derivation['original_report_sha256'],derivation['original_supporting_detail_sha256']]:
            require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest), 'Invalid provenance fingerprint.')
        report = blobs[report_id+'/report.md'].decode('utf-8')
        detail = blobs[report_id+'/supporting_detail.md'].decode('utf-8')
        require(bool(report.strip()) and bool(detail.strip()),'Published report content is empty.')
        return {'label':local.CATALOG[report_id]['label'],'report':report,'supporting_detail':detail,
                'verification':value,'publication_content_approval':approval,'scope':SCOPE}
    except local.ReportUnavailable:
        raise
    except (OSError,UnicodeError,ValueError,KeyError,TypeError,AttributeError):
        raise local.ReportUnavailable('Public snapshot files are missing, malformed or inconsistent.') from None


def render_public_reports(*, root=None):
    with st.container(horizontal=True,horizontal_alignment='center'):
        with st.container(width=1100,key='quarterly-reading-column'):
            st.title('Quarterly Reports')
            st.caption('Curated public snapshots of existing investor presentations.')
            selected = st.selectbox('Report',list(REPORT_IDS),format_func=lambda key:local.CATALOG[key]['label'])
            try:
                saved = load_public_report(selected,root=root)
            except local.ReportUnavailable as exc:
                st.error('Public report unavailable. '+str(exc))
                return
            st.info(saved['scope'])
            st.caption('Full private lineage was checked during curation, not reproduced here. Original-record hashes are provenance references.')
            st.success('Publication content: owner-approved for these exact public files, subject to rights restrictions.')
            st.warning('Content approval is not legal clearance or issuer permission. No specific rights restriction was identified in the local review.')
            auto,semantic,presentation = st.columns(3)
            with auto:
                st.success('Saved automatic evaluation: Passed')
            with semantic:
                if selected=='jpm_2026_q2':
                    st.info('Semantic acceptance documented in M006; archived review records pending.')
                else:
                    st.success('Semantic review: Passed in saved original records')
            with presentation:
                if selected=='cat_2026_q1':
                    st.info('Original report: hash-bound presentation approval. This derivative is not covered.')
                else:
                    milestone='M004' if selected=='msft_fy2026_q1' else 'M006'
                    st.info('Presentation acceptance documented in '+milestone+'; archived record pending. No final hash-bound approval.')
            st.caption('Review labels embedded in the report describe its original generation state; use the evidence and scope above.')
            st.markdown(local.report_markdown(saved['report']),unsafe_allow_html=False)
            st.subheader('Public supporting detail',anchor='supporting-detail')
            with st.expander('Verified financial tables and SEC sources',expanded=False):
                st.markdown(local.report_markdown(saved['supporting_detail']),unsafe_allow_html=False)

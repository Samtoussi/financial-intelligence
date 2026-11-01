"""Read-only display of selected pinned, locally saved quarterly presentations."""
import hashlib
import json
import re
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
CAT_APPROVAL = Path('evals/reports/m005/approvals/20261031T142017Z_c0eb8813')
CATALOG = {
    'cat_2026_q1': {
        'label': 'Caterpillar (CAT) - Q1 2026',
        'directory': Path('evals/reports/m005/eps-context-presentations/20261031T135903Z_3670fe1a'),
        'identity': {'ticker':'CAT', 'form':'10-Q', 'accession':'0000018230-26-000021',
                     'fiscal_period':'FY2026 Q1', 'period_start':'2026-01-01', 'period_end':'2026-03-31'},
        'presentation_version': 'm005-presentation-v1',
    },
    'jpm_2026_q2': {
        'label': 'JPMorgan Chase (JPM) - Q2 2026',
        'directory': Path('evals/reports/m006/final-presentations/step5_20261031T174931Z_63f650d6'),
        'identity': {'ticker':'JPM', 'form':'10-Q', 'accession':'0001628280-26-054343',
                     'fiscal_period':'FY2026 Q2', 'report_date':'2026-06-30'},
        'presentation_version': 'm006-financial-presentation-v1',
    },
    'msft_fy2026_q1': {
        'label': 'Microsoft (MSFT) - FY2026 Q1 (Jul-Sep 2025)',
        'directory': Path('evals/reports/m004/20261030T215529Z_4edc6a5c'),
        'source_run': Path('evals/reports/m003/20261030T211637Z_de30375b'),
        'identity': {'ticker':'MSFT', 'form':'10-Q', 'accession':'0001193125-25-256321',
                     'fiscal_period':'FY2026 Q1', 'period_start':'2025-07-01', 'period_end':'2025-09-30',
                     'prior_start':'2024-07-01', 'prior_end':'2024-09-30'},
        'presentation_version': 'm004-a-v2',
    },
}


class ReportUnavailable(ValueError):
    """Selected saved artifacts are missing, malformed, or inconsistent."""


def _require(condition, message):
    if not condition:
        raise ReportUnavailable(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _read(root, path):
    target = (root / path).resolve()
    _require(target.is_relative_to(root.resolve()), 'Saved artifact location is invalid.')
    return target.read_bytes()


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'Saved metadata contains duplicate fields.')
            result[key] = value
        return result
    value = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
    _require(isinstance(value, dict), 'Saved metadata must be an object.')
    return value


def _passing(value, version):
    _require(value.get('evaluation_version') == version and value.get('automatic_pass') is True,
             'Saved automated evaluation did not pass.')
    failures = (value['financial']['failures'] + value['narrative']['failures']
                if version == 'm006-ai-eval-v1' else value['failures'])
    _require(failures == [], 'Saved automated evaluation contains failed checks.')


def _cat_approval(root, config, hashes):
    closure = _json(_read(root, CAT_APPROVAL/'closure.json'))
    _require(closure['presentation_directory'].replace('\\','/') == config['directory'].as_posix(),
             'Human approval belongs to a different presentation.')
    _require(closure['artifact_sha256']['report'] == hashes['report.md']
             and closure['artifact_sha256']['supporting_detail'] == hashes['supporting_detail.md'],
             'Human approval does not match the selected report files.')
    records = {}
    for name in ('oracle_review.json','review.json','presentation_review.json','reviewed_evaluation.json'):
        data = _read(root, CAT_APPROVAL/name)
        _require(_digest(data) == closure['approval_record_sha256'][name],
                 'Human approval evidence has changed.')
        records[name] = _json(data)
    for name in ('oracle_review.json','presentation_review.json'):
        review = records[name]
        _require(review.get('status') == 'pass' and isinstance(review.get('reviewer'),str)
                 and bool(review['reviewer'].strip()), 'Human approval is incomplete.')
    review = records['presentation_review.json']
    _require(review['report_sha256'] == hashes['report.md']
             and review['supporting_detail_sha256'] == hashes['supporting_detail.md'],
             'Presentation approval hashes do not match.')
    semantics = records['review.json']
    expected = {'gaap_vs_non_gaap','segment_comparability','sales_volume_and_price'}
    _require(set(semantics) == expected and all(r.get('status') == 'pass'
        and isinstance(r.get('reviewer'),str) and bool(r['reviewer'].strip()) for r in semantics.values()),
        'Human semantic approval is incomplete.')
    reviewed = records['reviewed_evaluation.json']
    _passing(reviewed, 'm005-eval-v3')
    _require(reviewed.get('overall_pass') is True and closure.get('m005_overall_approved') is True
        and closure.get('oracle_review_status') == 'pass' and closure.get('presentation_review_status') == 'pass'
        and closure.get('semantic_review_statuses') == dict.fromkeys(expected,'pass'),
        'Human approval has not passed.')


def _msft_reviewed_gate(root, config, presentation_evaluation, review):
    """One existing M004 presentation, bound to its explicit reviewed M003 run."""
    _passing(presentation_evaluation,'m004-a-eval-v2')
    _require(presentation_evaluation.get('m003_gate_pass') is True
        and presentation_evaluation.get('overall_pass') is False
        and presentation_evaluation.get('manual_review_status') == 'pending_manual_review'
        and review.get('status') == 'pending_manual_review', 'Archived MSFT presentation status is inconsistent.')
    manifest = _json(_read(root,config['directory']/'input_manifest.json'))
    source = config['source_run']
    # The historical manifest contains a Windows absolute path. Validate its
    # exact selected-run suffix, but never use it as a filesystem read target.
    recorded = manifest['input_directory'].replace('\\','/').rstrip('/')
    _require(manifest.get('renderer_version') == 'm004-a-v2'
        and manifest.get('profile') == 'msft_fy2026_q1'
        and (recorded == source.as_posix() or recorded.endswith('/'+source.as_posix())),
        'MSFT source-input manifest belongs to a different run or profile.')
    hashes = manifest['input_sha256']
    required = {'evaluation.json','run.json','source.json','review.json','generated.json'}
    _require(isinstance(hashes,dict) and required <= set(hashes), 'MSFT source-input manifest is incomplete.')
    inputs = {}
    for name,expected in hashes.items():
        _require(isinstance(name,str) and name not in ('.','..') and '/' not in name and '\\' not in name and ':' not in name,
            'MSFT source-input manifest contains an invalid filename.')
        data = _read(root,source/name)
        _require(_digest(data) == expected, 'MSFT source-input lineage hashes do not match.')
        if name in required: inputs[name] = _json(data)
    gate_data = _read(root,config['directory']/'m003_gate.json')
    _require(_digest(gate_data) == hashes['evaluation.json'], 'MSFT saved gate differs from its reviewed source evaluation.')
    gate = _json(gate_data);_passing(gate,'m003-eval-v1')
    _require(gate.get('overall_pass') is True and gate.get('metadata_pass') is True
        and gate.get('citation_integrity_pass') is True and gate.get('quote_membership_pass') is True,
        'MSFT financial, citation or semantic gate did not pass.')
    for field,expected in [('financial_values',14),('yoy_changes',7),('table_evidence_support',7)]:
        counter = gate[field]
        _require(type(counter.get('passed')) is int and type(counter.get('total')) is int
            and counter == {'passed':expected,'total':expected}, 'MSFT saved financial checks are incomplete.')
    identity = config['identity'];metadata = inputs['source.json'];run = inputs['run.json']
    _require(all(metadata.get(k) == identity[k] for k in ('ticker','form','accession'))
        and metadata.get('report_date') == identity['period_end']
        and all(inputs['generated.json']['report'].get(k) == v for k,v in identity.items())
        and run.get('profile') == 'msft_fy2026_q1' and run.get('status') == 'completed_reviewed'
        and run.get('overall_pass') is True and run.get('generation_mode') == 'm003-v2',
        'MSFT reviewed source identity, period or run state does not match.')
    expected_topics = {'gaap_vs_non_gaap','segment_comparability','azure_growth_vs_cloud_margin'}
    semantic = inputs['review.json'];reviews = gate['manual_reviews']
    _require(set(semantic) == expected_topics and isinstance(reviews,list) and len(reviews) == 3
        and {r['id'] for r in reviews} == expected_topics, 'MSFT semantic review cases are incomplete.')
    for recorded_review in reviews:
        approved = semantic[recorded_review['id']]
        _require(approved.get('status') == 'pass' and recorded_review.get('status') == 'pass'
            and all(isinstance(approved.get(k),str) and approved[k].strip() for k in ('reviewer','rationale'))
            and all(recorded_review.get(k) == approved.get(k) for k in ('reviewer','rationale','evidence_ids'))
            and isinstance(approved.get('evidence_ids'),list) and bool(approved['evidence_ids']),
            'MSFT semantic reviews have not passed or differ from the saved gate.')
    _require(bool(_read(root,Path('evals/M004.md')).decode('utf-8-sig').strip()),
        'M004 presentation-acceptance documentation is unavailable.')


def load_report(report_id, *, root=None):
    """Validate saved metadata and bytes; never generate or re-evaluate a report."""
    _require(report_id in CATALOG, 'Unknown quarterly report.')
    root = Path(root) if root is not None else ROOT
    config = CATALOG[report_id];base = config['directory']
    try:
        blobs = {name:_read(root,base/name) for name in
                 ('report.md','supporting_detail.md','presentation.json','presentation_evaluation.json','review_template.json')}
        report, detail = (blobs[name].decode('utf-8') for name in ('report.md','supporting_detail.md'))
        _require(bool(report.strip()) and bool(detail.strip()), 'Saved report content is empty.')
        presentation = _json(blobs['presentation.json']);identity = presentation['report']
        _require(presentation.get('version') == config['presentation_version']
            and all(identity.get(k) == v for k,v in config['identity'].items()),
            'Saved report identity or reporting period does not match.')
        hashes = {name:_digest(blobs[name]) for name in ('report.md','supporting_detail.md')}
        review = _json(blobs['review_template.json'])
        _require(review['report_sha256'] == hashes['report.md']
            and review['supporting_detail_sha256'] == hashes['supporting_detail.md'],
            'Saved report files do not match their verification hashes.')
        evaluation = _json(blobs['presentation_evaluation.json'])
        if report_id == 'cat_2026_q1':
            _passing(evaluation,'m005-presentation-eval-v1')
            gate = _read(root,base/'m003_gate.json')
            provenance = _json(_read(root,base/'input_manifest.json'))
            _require(provenance.get('profile') == report_id
                and provenance['input_sha256']['evaluation.json'] == _digest(gate),
                'Saved CAT evaluation provenance does not match.')
            _passing(_json(gate),'m005-eval-v3')
            _cat_approval(root,config,hashes)
            human_status = 'Approved (validated hash-bound review)'
            human_note = 'Separate human approval records match these exact report files.'
        elif report_id == 'msft_fy2026_q1':
            _msft_reviewed_gate(root,config,evaluation,review)
            human_status = 'Semantic review passed; presentation acceptance documented'
            human_note = ('The archived presentation record remains pending. Human presentation acceptance '
                          'is documented in M004; no hash-bound final presentation approval is claimed.')
        else:
            _passing(evaluation,'m006-ai-presentation-v1')
            manifest = _json(_read(root,base/'artifact_hashes.json'))
            for name,data in blobs.items():
                _require(manifest[name] == _digest(data), 'Saved presentation metadata or content has changed.')
            data = _read(root,base/'evaluation.json')
            _require(manifest['evaluation.json'] == _digest(data), 'Saved evaluation has changed.')
            saved = _json(data);_passing(saved,'m006-ai-eval-v1')
            _require(saved['financial']['automatic_pass'] is True and saved['narrative']['automatic_pass'] is True
                and saved['source_context_pass'] is True and saved['assembled_response_match'] is True,
                'Saved financial, narrative or source checks did not pass.')
            _require(saved.get('overall_pass') is False and evaluation.get('overall_pass') is False
                and evaluation.get('review_status') == 'pending_manual_review'
                and review.get('status') == 'pending_manual_review', 'Archived review status is inconsistent.')
            data = _read(root,base/'review_context.json')
            _require(manifest['review_context.json'] == _digest(data)
                and _json(data).get('user_stated_financial_and_semantic_review_passed') is True,
                'Saved human-review context is missing or inconsistent.')
            _require(bool(_read(root,Path('evals/M006.md')).decode('utf-8-sig').strip()),
                     'Milestone approval documentation is unavailable.')
            human_status = 'Pending in saved review records'
            human_note = ('Subsequent human approval is documented in the M006 milestone. '
                          'A final hash-bound human approval record is not present.')
        return {'label':config['label'],'report':report,'supporting_detail':detail,
                'automated_status':'Passed','human_status':human_status,'human_note':human_note}
    except ReportUnavailable:
        raise
    except (OSError,UnicodeError,ValueError,KeyError,TypeError,AttributeError):
        raise ReportUnavailable('Required saved artifacts are missing, malformed or inconsistent.') from None


# Preserve code/evidence and link destinations while escaping currency in prose.
# This targets the saved financial Markdown, not a general Markdown parser.
_LITERAL_MARKDOWN = re.compile(
    r'(?P<fence>^ {0,3}(?P<marker>`{3,}|~{3,})[^\r\n]*\r?\n.*?^ {0,3}(?P=marker)[ \t]*(?:\r?\n|$))'
    r'|(?P<code>(?P<ticks>`+)(?:(?!(?P=ticks)).)*?(?P=ticks)(?!`))'
    r'|(?P<reference>^ {0,3}\[[^\]\r\n]+\]:[^\r\n]*)'
    r'|(?P<destination>\]\((?:\\.|[^)\\\r\n])*\))'
    r'|(?P<url>https?://[^\s<>]+)', re.MULTILINE | re.DOTALL)


def report_markdown(value):
    """Display literal currency and internal links without changing saved files."""
    def currency(prose):
        # Preserve existing escapes; repeated rendering must not add slashes.
        return re.sub(r'(\\*)\$(?=\s*[-+(]?\d)',
            lambda m: m[0] if len(m[1]) % 2 else m[1] + r'\$', prose)

    parts = [];position = 0
    for match in _LITERAL_MARKDOWN.finditer(value):
        parts.append(currency(value[position:match.start()]))
        literal = match[0]
        if match.lastgroup == 'destination' and literal == '](supporting_detail.md)':
            literal = '](#supporting-detail)'
        parts.append(literal)
        position = match.end()
    parts.append(currency(value[position:]))
    return ''.join(parts)


def render_quarterly_reports(*, public=False):
    if public:
        from src.ui.public_quarterly_reports import render_public_reports
        return render_public_reports(root=ROOT)

    with st.container(horizontal=True,horizontal_alignment='center'):
        # Native width caps at the parent width on small screens; tables keep
        # their normal Streamlit overflow behavior without global CSS changes.
        with st.container(width=1100,key='quarterly-reading-column'):
            st.title('Quarterly Reports')
            st.caption('Existing SEC-grounded investor reports. No generation is performed here.')
            selected = st.selectbox('Report',list(CATALOG),format_func=lambda key:CATALOG[key]['label'])
            try:
                saved = load_report(selected)
            except ReportUnavailable as exc:
                st.error('This saved report is unavailable. ' + str(exc))
                return
            st.subheader('Current review evidence')
            if selected == 'msft_fy2026_q1':
                automated,semantic,human = st.columns(3)
                with semantic:
                    st.success('Semantic review: Passed (saved M003 gate)')
            else:
                automated,human = st.columns(2)
            with automated:
                st.success('Saved automated evaluation: ' + saved['automated_status'])
            with human:
                if selected == 'cat_2026_q1':
                    st.success('Human review: ' + saved['human_status'])
                elif selected == 'msft_fy2026_q1':
                    st.info('Human presentation acceptance: Documented in M004')
                else:
                    st.info('Human review: ' + saved['human_status'])
            st.caption(saved['human_note'])
            if selected == 'jpm_2026_q2':
                st.markdown('[M006 milestone documentation](https://github.com/Samtoussi/financial-intelligence/blob/main/evals/M006.md)')
            elif selected == 'msft_fy2026_q1':
                st.markdown('[M004 presentation acceptance](https://github.com/Samtoussi/financial-intelligence/blob/main/evals/M004.md)')
            st.caption('Review labels inside the archived report describe its original generation state. '
                       'The current review evidence above is authoritative, including the separate milestone documentation notes.')
            st.markdown(report_markdown(saved['report']),unsafe_allow_html=False)
            st.subheader('Supporting detail',anchor='supporting-detail')
            with st.expander('Detailed source evidence',expanded=False):
                st.markdown(report_markdown(saved['supporting_detail']),unsafe_allow_html=False)

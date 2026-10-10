"""RFQFlow demo UI: all extraction, matching and pricing remain in FastAPI."""
import os
import sys
from pathlib import Path

import httpx
import streamlit as st

# Support streamlit run frontend/app.py from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.demo_quote import COMPLETE, AMBIGUOUS

API = os.getenv('RFQFLOW_API_URL', 'http://127.0.0.1:8000').rstrip('/')
st.set_page_config(page_title='RFQFlow', page_icon='⚙️', layout='wide')


def request(path, **kwargs):
    try:
        with httpx.Client(base_url=API, timeout=180) as client:
            response = client.post(path, **kwargs)
        if response.is_error:
            if response.status_code == 404:
                raise ValueError('The RFQ session has expired. Process the RFQ again.')
            if response.status_code == 503 or response.status_code >= 500:
                raise ValueError('The backend could not finish processing. Check Nicrron access and the seeded supplier index, then retry.')
            detail = response.json().get('detail', 'Request rejected')
            if isinstance(detail, list):
                detail = '; '.join(str(d.get('msg', 'Invalid input')) for d in detail)
            raise ValueError(str(detail))
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('The backend returned an unexpected response.')
        return result
    except httpx.TimeoutException:
        raise ValueError('Processing timed out. The backend may still be running; wait briefly before retrying.') from None
    except httpx.RequestError:
        raise ValueError('Cannot reach the backend. Start FastAPI and check RFQFLOW_API_URL.') from None
    except (TypeError, KeyError):
        raise ValueError('The backend returned an unexpected response.') from None


def load_sample(text):
    st.session_state['rfq_text'] = text
    st.session_state['input_mode'] = 'Paste text'
    st.session_state.pop('result', None)


def process_upload(upload):
    parsed = request('/api/parse-file', files={'file': (upload.name, upload.getvalue(), upload.type or 'application/octet-stream')})
    # Reuse the actual parsed object, including filename/page/sheet/row references.
    return request('/api/quote/run', json={'parsed_rfq': parsed})


st.title('RFQFlow')
st.markdown('### AI-Powered Industrial RFQ-to-Quote')
st.caption('RudCo · Industrial sourcing demo')
st.warning('DEMO DATA — Synthetic supplier pricing')
st.caption('Market competitiveness not established.')

with st.sidebar:
    st.header('RFQ input')
    st.button('Load Complete RFQ', on_click=load_sample, args=(COMPLETE,), use_container_width=True)
    st.button('Load Ambiguous RFQ', on_click=load_sample, args=(AMBIGUOUS,), use_container_width=True)
    mode = st.radio('Input method', ['Paste text', 'Upload document'], key='input_mode')
    upload = None
    text = ''
    if mode == 'Paste text':
        text = st.text_area('Buyer request', key='rfq_text', height=260, placeholder='Paste material descriptions, quantities, dimensions and requirements…')
    else:
        upload = st.file_uploader('RFQ document', type=['pdf', 'xlsx', 'csv', 'eml', 'txt'])
        st.caption('Maximum 10 MB. Scanned PDFs require OCR and are unsupported.')
    if st.button('Process RFQ', type='primary', use_container_width=True):
        st.session_state.pop('result', None)
        if (mode == 'Paste text' and not text.strip()) or (mode != 'Paste text' and upload is None):
            st.error('Enter an RFQ or upload a document first.')
        elif upload is not None and upload.size > 10 * 1024 * 1024:
            st.error('File exceeds the 10 MB limit.')
        else:
            try:
                with st.spinner('Extracting requirements and preparing quotation…'):
                    st.session_state['result'] = process_upload(upload) if upload is not None else request('/api/quote/run', json={'text': text})
            except ValueError as exc:
                st.error(str(exc))
    st.divider()
    st.caption('Single-worker demo. Buyer sessions reset when FastAPI restarts.')

result = st.session_state.get('result')
if not result:
    st.info('Paste or upload an RFQ, then select Process RFQ. Use a sample to explore the complete or clarification workflow.')
    st.stop()

status = result['overall_status']
cols = st.columns(3)
cols[0].metric('Workflow status', status.replace('_', ' '))
cols[1].metric('RFQ lines', len(result['items']))
cols[2].metric('Revision', result['revision'])
st.caption(f"RFQ ID: {result['rfq_id']}")
if status == 'QUOTE_READY':
    st.success('Demo quotation ready. Specifications matched; no unresolved required compliance.')
elif status == 'NEEDS_CLARIFICATION':
    st.warning('Buyer clarification required. No approved quotation is available.')
else:
    st.error('Quotation blocked. Review the missing information and evidence below.')

st.subheader('Extracted specifications')
parsed = result['parsed_rfq']
parsed_by_id = {i['line_id']: i for i in parsed['items']}
rows = []
for item in parsed['items']:
    s, ref = item['specification'], item['source_reference']
    location = ' · '.join(f'{k}: {ref[k]}' for k in ('source_filename', 'page', 'sheet', 'row') if ref.get(k) is not None)
    rows.append({'Line ID': item['line_id'], 'Material': s.get('material_family'), 'Grade': s.get('material_grade'), 'Form': s.get('product_form'), 'Thickness': s['thickness'].get('raw'), 'Width': s['width'].get('raw'), 'Length': s['length'].get('raw'), 'Quantity': s.get('quantity'), 'Units': s.get('quantity_unit'), 'ASTM standard': s.get('requested_standard'), 'Certifications': ', '.join(s.get('requested_certifications', [])), 'Extraction status': item['extraction_status'], 'Source': location or None})
st.dataframe(rows, use_container_width=True, hide_index=True)
with st.expander('Source text and extraction warnings'):
    st.text(parsed['original_text'])
    for item in parsed['items']:
        st.markdown(f"**{item['line_id']}**")
        st.json({'source_reference': item['source_reference'], 'missing_fields': item['missing_fields'], 'ambiguities': item['ambiguities']})

questions = result.get('clarification_questions', [])
if status == 'NEEDS_CLARIFICATION' and questions:
    st.subheader('Buyer clarification')
    with st.form(f"clarify_{result['rfq_id']}_{result['revision']}"):
        answers = []
        for q in questions:
            field = q['field']
            value = st.text_input(q['question'], key=f"answer_{result['rfq_id']}_{result['revision']}_{q['line_id']}_{field}", placeholder='Explicit measurement, e.g. 48 in' if field in ('thickness', 'width', 'length') else 'Enter your answer')
            if value.strip():
                answers.append({'line_id': q['line_id'], 'field': field, 'value': value.strip()})
        if st.form_submit_button('Submit Clarifications', type='primary'):
            if not answers:
                st.warning('Provide at least one answer. Missing answers will remain unresolved.')
            else:
                try:
                    with st.spinner('Revalidating specifications and updating quotation…'):
                        st.session_state['result'] = request('/api/quote/clarify', json={'rfq_id': result['rfq_id'], 'answers': answers})
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

st.subheader('Supplier matches')
for item in result['items']:
    with st.expander(f"{item['line_id']} · {item['status'].replace('_', ' ')}", expanded=True):
        selected = item.get('selected_product')
        if selected:
            st.write(f"Selected compatible product: {selected['sku']} · {selected['supplier_name']}")
            st.caption('Selection establishes dimensional/material compatibility only. Availability is not established.')
        candidates = item.get('supplier_candidates', [])
        if candidates:
            st.dataframe([{'SKU': c['sku'], 'Supplier': c['supplier_name'], 'Product': c['description'], 'Material': c['material_family'], 'Grade': c['material_grade'], 'Thickness (in)': c['thickness_in'], 'Width (in)': c['width_in'], 'Length (in)': c['length_in'], 'Retrieval status': c['validation_status'], 'Warnings': '; '.join(c.get('potential_conflicts', [])), 'Evidence source': c['source_id']} for c in candidates], use_container_width=True, hide_index=True)
            st.caption('Retrieved candidates are not automatically approved. Selection and quote readiness are separate decisions.')
        else:
            st.info('No supplier candidates available for this line. Resolve specifications or review the catalog match.')
        compliance = item['compliance']
        if compliance['status'] == 'UNVERIFIED':
            st.warning('Compliance UNVERIFIED — required evidence is unavailable or specifications remain unresolved.')
        else:
            st.caption(f"Compliance: {compliance['status']}")
        if compliance.get('checks'):
            st.dataframe(compliance['checks'], use_container_width=True, hide_index=True)

st.subheader('Quotation')
quote = result.get('final_quotation')
if status == 'QUOTE_READY' and quote:
    st.warning('DEMO DATA — Synthetic supplier pricing')
    st.dataframe([{'Item': l['line_id'], 'SKU': l['sku'], 'Material': parsed_by_id[l['line_id']]['specification'].get('material_family'), 'Grade': parsed_by_id[l['line_id']]['specification'].get('material_grade'), 'Quantity': l['quantity'], 'Unit price (USD)': l['unit_selling_price'], 'Line total (USD)': l['line_total']} for l in quote['lines']], use_container_width=True, hide_index=True)
    a, b = st.columns(2)
    a.metric('Subtotal (USD)', quote['subtotal'])
    b.metric('Grand total (USD)', quote['grand_total'])
    st.caption(quote['terms'])
    st.caption(quote['market_assessment'])
else:
    st.info('No approved quotation. Complete the required clarification or resolve blockers.')
for blocker in result.get('blockers', []):
    st.error(blocker)
with st.expander('Full workflow response and evidence'):
    st.json(result)

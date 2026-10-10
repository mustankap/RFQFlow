import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app.ingestion.parser import build_parsed_rfq
from backend.app.retrieval.vector_search import RetrievalIndex,load_products
from backend.app.workflow.service import QuoteWorkflow
from backend.app.workflow.router import Answer
from backend.app.main import app

COMPLETE='12 pcs 304 stainless steel sheet 0.060 in 48 x 96 in\n5 pcs A36 carbon steel plate 0.25 in 48 x 96 in'
AMBIGUOUS='20 pcs 304 SS sheet 16ga 4x8'

def fixture_parser(text):
    lines=[]
    for raw in text.splitlines():
        if not ("sheet" in raw or "plate" in raw): continue
        steel='304' in raw
        ambiguous='16ga' in raw
        lines.append(dict(raw_input=raw,material='stainless steel' if steel else 'carbon steel',grade='304' if steel else 'A36',form='sheet' if steel else 'plate',quantity=20 if ambiguous else (12 if steel else 5),quantity_unit='pieces',thickness_raw='16ga' if ambiguous else ('0.060 in' if steel else '0.25 in'),width_raw='4' if ambiguous else '48',length_raw='8' if ambiguous else '96',dimension_unit=None if ambiguous else 'in',certifications=['MTR'] if 'MTR' in text else []))
    return build_parsed_rfq({'lines':lines},text)

class Embedder:
    model='test-workflow-only'
    def embed(self,texts):return [[1.,0.,0.] for _ in texts]

@pytest.fixture
def workflow(tmp_path):
    index=RetrievalIndex(tmp_path/'index',Embedder())
    catalog=load_products(Path('backend/data/fixtures/retrieval/supplier_catalog.json'))
    index.build_index(catalog.products,catalog.catalog_version)
    return QuoteWorkflow(parser=fixture_parser,retriever=index)

def test_complete_quote(workflow):
    out=workflow.run(COMPLETE)
    assert out['overall_status']=='QUOTE_READY'
    assert out['final_quotation']['grand_total']=='1980.00'
    assert len(out['final_quotation']['lines'])==2
    assert all(i['pricing']['label']=='DEMO DATA' for i in out['items'])

def test_ambiguous_resume_preserves_source(workflow):
    out=workflow.run(AMBIGUOUS)
    assert out['overall_status']=='NEEDS_CLARIFICATION'
    assert out['final_quotation'] is None
    assert {q['field'] for q in out['clarification_questions']}=={'thickness','width','length'}
    out=workflow.clarify(out['rfq_id'],[Answer(line_id='LINE-001',field=k,value=v) for k,v in [('thickness','0.060 in'),('width','48 in'),('length','96 in')]])
    assert out['overall_status']=='QUOTE_READY'
    assert out['parsed_rfq']['original_text']==AMBIGUOUS
    assert out['parsed_rfq']['items'][0]['original_text']==AMBIGUOUS
    assert len(out['buyer_answers'])==3

def test_compliance_blocks(workflow):
    out=workflow.run(COMPLETE+'\nInclude MTRs for all materials.')
    assert out['final_quotation'] is None
    assert all(i['compliance']['status']=='UNVERIFIED' for i in out['items'])

def test_unresolved_answer_stays_blocked(workflow):
    out=workflow.run(AMBIGUOUS)
    out=workflow.clarify(out['rfq_id'],[Answer(line_id='LINE-001',field='width',value='4')])
    assert out['overall_status']=='NEEDS_CLARIFICATION'

def test_cross_line_grade_and_omission():
    parsed=fixture_parser(COMPLETE)
    from backend.app.ingestion.parser import build_parsed_rfq
    data={'lines':[dict(raw_input=COMPLETE.splitlines()[0],material='stainless steel',grade='A36',form='sheet',quantity=12,quantity_unit='pieces',thickness_raw='0.060 in',width_raw='48',length_raw='96',dimension_unit='in')]}
    result=build_parsed_rfq(data,COMPLETE)
    assert result.items[0].specification.material_grade is None
    assert result.unparsed_segments

def test_api_run_resume(workflow,monkeypatch):
    import backend.app.workflow.router as routes
    monkeypatch.setattr(routes,'workflow',workflow)
    with TestClient(app) as client:
        r=client.post('/api/quote/run',json={'text':AMBIGUOUS})
        assert r.status_code==200
        r=client.post('/api/quote/clarify',json={'rfq_id':r.json()['rfq_id'],'answers':[{'line_id':'LINE-001','field':k,'value':v} for k,v in [('thickness','0.060 in'),('width','48 in'),('length','96 in')]]})
        assert r.status_code==200 and r.json()['overall_status']=='QUOTE_READY'
        assert client.get('/health').status_code==200

@pytest.mark.parametrize('requirement',['ASTM A240','Country of origin must be USA'])
def test_source_compliance_survives_missed_extraction(workflow,requirement):
    out=workflow.run(COMPLETE+'\n'+requirement)
    assert out['overall_status']=='BLOCKED'
    assert out['final_quotation'] is None
    assert all(i['compliance']['status']=='UNVERIFIED' for i in out['items'])

def test_wrong_size_never_selected(workflow):
    out=workflow.run(COMPLETE)
    out=workflow.clarify(out['rfq_id'],[Answer(line_id='LINE-001',field='width',value='47 in')])
    assert out['overall_status']=='BLOCKED'
    assert out['items'][0]['selected_product'] is None
    assert out['final_quotation'] is None

import json
import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import chromadb
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.retrieval_routes import get_service
from backend.app.retrieval.adapters import adapt_rfq, dimensions_in
from backend.app.retrieval.api import app
from backend.app.retrieval.demo import seed_demo
from backend.app.retrieval.evaluation import evaluate
from backend.app.retrieval.repository import SQLiteRepository
from backend.app.retrieval.service import RetrievalService
from backend.app.retrieval.vector_search import IndexUnavailable, RetrievalIndex

FIXTURES = Path(__file__).parents[1]/'data/fixtures/retrieval'


class TestEmbeddings:
    """Storage/ranking tests only, not a semantic-quality evaluator."""
    __test__ = False
    model = 'test-only-vectors'

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[1.0,0.0,0.0] for _ in texts]


@pytest.fixture(autouse=True)
def no_remote_telemetry(monkeypatch):
    monkeypatch.delenv('PRISMTRACE_API_KEY', raising=False)
    monkeypatch.delenv('PRISMTRACE_PROJECT_ID', raising=False)


@pytest.fixture
def service(tmp_path):
    db = tmp_path/'demo.sqlite'
    seed_demo(db,FIXTURES/'supplier_catalog.json')
    result = RetrievalService(SQLiteRepository(db), RetrievalIndex(tmp_path/'chroma', TestEmbeddings()),
                              date(2026,10,10), tmp_path/'traces')
    result.build_index()
    return result


@pytest.fixture
def rfq():
    return json.loads((FIXTURES/'parsed_rfq_ideal.json').read_text())


def test_hybrid_sourced_evidence_and_multiple_vendors(service, rfq):
    result = service.retrieve_for_rfq(rfq)
    line = result.items[0]
    assert [c.catalog_id for c in line.supplier_candidates] == ['DEMO-SS304-060']
    assert line.supplier_candidates[0].retrieval_methods == ['sql','semantic']
    assert any(c.catalog_id == 'DEMO-SS304-120' for c in line.conflicting_candidates)
    assert any(c.catalog_id == 'DEMO-SS316-060' for c in line.conflicting_candidates)
    assert all(c.potential_conflicts for c in line.conflicting_candidates)
    assert len(line.supplier_prices) == 2
    assert line.supplier_prices[0].cost_per_unit == Decimal('100.00')
    assert line.supplier_prices[0].temporal_status == 'current'
    assert all(p.is_synthetic and p.source_id and p.source_reference for p in line.supplier_prices)
    assert len({i.line_id for i in result.items}) == 3
    assert result.items[1].supplier_prices == []
    assert any('No supplier_prices' in w for w in result.items[1].warnings)
    assert line.market_benchmarks[0].comparability == 'not_established'
    assert any('Surcharge' in w for w in line.market_benchmarks[0].warnings)


def test_customer_scope_stale_dates_and_missing_mtr(service, rfq):
    history = service.retrieve_historical_quotes('DEMO-SS304-060','CUST-A')
    assert [r.quote_id for r in history.historical_quotes] == ['SYNTH-H1']
    assert service.retrieve_historical_quotes('DEMO-SS304-060','UNKNOWN').historical_quotes == []
    history = service.retrieve_historical_quotes('DEMO-SS304-060')
    assert any(r.temporal_status == 'stale' for r in history.historical_quotes)
    rfq['items'][0]['specification']['requested_certifications'] = ['MTR']
    result = service.retrieve_for_rfq(rfq)
    assert any('Requested MTR evidence is missing' in w for w in result.items[0].warnings)
    assert result.items[0].compliance_evidence[0].verification_status == 'unverified'


def test_updated_spec_used_in_embedding_and_no_reindex(service, rfq):
    rfq['items'] = [rfq['items'][2]]
    rfq['items'][0]['specification']['material_grade'] = '5052'
    service.index.embedder.calls.clear()
    result = service.retrieve_for_rfq(rfq)
    assert result.items[0].supplier_candidates[0].catalog_id == 'DEMO-AL5052-250'
    assert len(service.index.embedder.calls) == 1
    assert '5052' in service.index.embedder.calls[0][0]
    assert '6061' not in service.index.embedder.calls[0][0]


def test_missing_grade_and_uncertain_values_not_invented(service, rfq):
    item = rfq['items'][2]
    item['specification']['material_grade'] = None
    item['specification']['width']['unit_status'] = 'inferred'
    result = service.retrieve_for_line(item)
    assert {c.grade for c in result.supplier_candidates} == {'6061','5052'}
    assert 'width 24' not in result.query_text
    assert all(any('width_in unresolved' in s for s in c.unchecked_requirements) for c in result.supplier_candidates)


def test_snapshot_change_degrades_then_reindexes(service, rfq):
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute("UPDATE product_catalog SET grade='999' WHERE catalog_id='DEMO-SS304-060'")
    result = service.retrieve_for_rfq(rfq)
    assert result.items[0].status == 'degraded'
    assert not result.items[0].supplier_candidates
    service.build_index()
    assert service.retrieve_for_rfq(rfq).items[0].status == 'no_candidates'


def test_deleted_products_not_returned(service, rfq):
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute("DELETE FROM product_catalog WHERE material='aluminum'")
    result = service.retrieve_for_rfq(rfq)
    assert result.items[2].supplier_candidates == []


def test_model_mismatch_and_dimension_change(service, rfq):
    with service.repository.snapshot() as repo:
        version = repo.catalog_version(repo.list_products())
    service.index.embedder.model='changed'
    with pytest.raises(IndexUnavailable):
        service.index.load_index(version)
    assert service.retrieve_for_rfq(rfq).items[0].status == 'degraded'
    service.index.embedder.model='test-only-vectors'
    service.index.embedder.embed=lambda texts:[[1,0] for _ in texts]
    assert service.retrieve_for_rfq(rfq).items[0].status == 'degraded'


def test_persistence_and_idempotent_index(service):
    service.index.embedder.calls.clear()
    assert service.build_index()['status']=='already_indexed'
    assert service.index.embedder.calls==[]
    with service.repository.snapshot() as repo:
        version=repo.catalog_version(repo.list_products())
    name=service.index.collection_name(version)
    code='import chromadb,sys; print(chromadb.PersistentClient(path=sys.argv[1]).get_collection(sys.argv[2],embedding_function=None).count())'
    result=subprocess.run([sys.executable,'-c',code,str(service.repository.path.parent/'chroma'),name],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='6'


def test_empty_catalog_and_sql_injection(service, rfq):
    malicious=rfq['items'][0]
    malicious['specification']['material_grade']="304' OR 1=1 --"
    assert not service.retrieve_for_line(malicious).supplier_candidates
    with service.repository.snapshot() as repo:
        assert len(repo.list_products())==6
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute('DELETE FROM product_catalog')
    assert service.build_index()['status']=='empty_catalog'
    assert not service.retrieve_for_line(malicious).supplier_candidates


def test_invalid_price_flagged(service):
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute("UPDATE vendor_pricing SET cost_per_unit='NaN' WHERE pricing_id=1")
    result=service.retrieve_supplier_prices('DEMO-SS304-060')
    assert len(result.supplier_prices)==1
    assert any('Invalid vendor_pricing' in w for w in result.warnings)


def test_legacy_d3_schema_is_read_only(tmp_path):
    db=tmp_path/'legacy.sqlite'
    with sqlite3.connect(db) as conn:
        conn.executescript('''
        CREATE TABLE product_catalog(catalog_id TEXT PRIMARY KEY, material TEXT NOT NULL, grade TEXT NOT NULL, form TEXT NOT NULL, dimensions TEXT NOT NULL, standard TEXT NOT NULL, compliance_flags TEXT);
        CREATE TABLE vendor_pricing(pricing_id INTEGER PRIMARY KEY AUTOINCREMENT, catalog_id TEXT, vendor_name TEXT NOT NULL, cost_per_unit REAL NOT NULL, unit_of_measure TEXT NOT NULL, lead_time_days INTEGER NOT NULL, FOREIGN KEY(catalog_id) REFERENCES product_catalog(catalog_id));
        CREATE TABLE historical_quotes(quote_id TEXT PRIMARY KEY,customer_name TEXT NOT NULL,raw_buyer_string TEXT NOT NULL,matched_catalog_id TEXT NOT NULL,final_quoted_unit_price REAL NOT NULL,compliance_verified TEXT NOT NULL,quote_date TEXT NOT NULL,FOREIGN KEY(matched_catalog_id) REFERENCES product_catalog(catalog_id));
        INSERT INTO product_catalog VALUES('P1','SS','304','sheet','16ga 4x8','ASTM','MTR');
        INSERT INTO vendor_pricing VALUES(1,'P1','Vendor',100.25,'per_sheet',5);
        INSERT INTO historical_quotes VALUES('H1','Customer','SS','P1',125.0,'yes','2026-09-01');
        ''')
    before=db.read_bytes()
    with SQLiteRepository(db).snapshot() as repo:
        p=repo.list_products()[0]
        assert p.thickness_in is None and p.standard is None and p.is_synthetic is None
        price=repo.evidence('P1','supplier_prices',date(2026,10,10)).supplier_prices[0]
        assert price.currency is None and price.temporal_status=='unknown'
        assert any('REAL' in w for w in price.warnings)
        assert repo.evidence('P1','compliance_evidence',date(2026,10,10)).compliance_evidence==[]
        assert repo.evidence('P1','historical_quotes',date(2026,10,10),'CUST-A').historical_quotes==[]
        with pytest.raises(sqlite3.OperationalError):
            repo.connection.execute('DELETE FROM product_catalog')
    assert before==db.read_bytes()


def test_flat_contract_and_dimension_ambiguity():
    rfq=adapt_rfq({'raw_input':'RFQ','material':'SS','grade':None,'form':'sheet','dimensions':'1/4 x 48 x 96 in','quantity':10,'standard':'ASTM'})
    assert rfq.items[0].specification.thickness.normalized_inches==.25
    assert rfq.items[0].specification.material_grade is None
    assert rfq.items[0].specification.requested_standard is None
    assert rfq.items[0].specification.quantity_unit is None
    assert dimensions_in('16ga 4x8')==(None,None,None)
    assert dimensions_in('0.25 x 48 x 96')==(None,None,None)
    with pytest.raises(ValidationError):
        adapt_rfq({'raw_input':'RFQ','quantity':-1})


def test_api_response_validation_and_failures(service, rfq):
    app.dependency_overrides[get_service]=lambda:service
    try:
        with TestClient(app) as client:
            result=client.post('/api/retrieval/rfq',json={'parsed_rfq':rfq})
            assert result.status_code==200
            assert result.json()['items'][0]['supplier_prices'][0]['cost_per_unit']=='100.00'
            assert client.post('/api/retrieval/rfq',json={'parsed_rfq':rfq,'top_k':0}).status_code==422
            broken=dict(rfq,items=[rfq['items'][0],rfq['items'][0]])
            assert client.post('/api/retrieval/rfq',json={'parsed_rfq':broken}).status_code==422
            assert client.get('/api/retrieval/products/UNKNOWN/prices').json()['supplier_prices']==[]
            service.repository.path=service.repository.path.parent/'missing.sqlite'
            assert client.post('/api/retrieval/rfq',json={'parsed_rfq':rfq}).status_code==503
    finally:
        app.dependency_overrides.clear()


def test_full_labeled_fixtures_and_local_trace(service):
    report=evaluate(service,FIXTURES/'evaluation_cases.json')
    assert report['passed']==report['cases']==12
    files=list(service.trace_dir.glob('*.json'))
    assert files
    trace=json.loads(files[-1].read_text())
    assert trace['agent_name']=='rudco-rfq-phase1'
    assert trace['prism_status']=='not_configured'


def test_seed_does_not_overwrite(service):
    with pytest.raises(FileExistsError):
        seed_demo(service.repository.path,FIXTURES/'supplier_catalog.json')


def test_null_provenance_columns_fall_back_to_source_document(service):
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute('ALTER TABLE vendor_pricing ADD COLUMN source_date TEXT')
        # Demo source_date is NULL, while source_documents has an effective date.
    price=service.retrieve_supplier_prices('DEMO-SS304-060').supplier_prices[0]
    assert price.source_date==date(2026,10,1)


def test_aliases_and_lowercase_match_both_searches(service):
    result=service.search_supplier_catalog({'material':'SS','grade':'304','form':'SHEET',
        'dimensions':'0.060 x 48 x 96 in','quantity':12})
    assert result.supplier_candidates[0].retrieval_methods==['sql','semantic']


def test_wrong_metric_and_incomplete_index(service):
    with service.repository.snapshot() as repo:
        version=repo.catalog_version(repo.list_products())
    collection=service.index.load_index(version)
    collection.modify(metadata={**collection.metadata,'state':'building'})
    with pytest.raises(IndexUnavailable, match='incomplete'):
        service.index.load_index(version)
    service.build_index()
    assert service.index.load_index(version).count()==6


def test_malformed_items_are_rejected():
    for items in ['bad', [None], [], [{}]*101]:
        with pytest.raises(ValueError):
            adapt_rfq({'rfq_id':'RFQ','items':items})


def test_snapshot_closes_connection(service):
    with service.repository.snapshot() as repo:
        connection=repo.connection
        assert connection.execute('SELECT 1').fetchone()[0]==1
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        connection.execute('SELECT 1')


def test_sheet_pair_has_no_implied_thickness():
    assert dimensions_in('48x96 in','Sheet')==(None,48,96)
    assert dimensions_in('4x8 ft','plate')==(None,48,96)
    assert dimensions_in('48x96','sheet')==(None,None,None)
    assert dimensions_in('2 in SCH 40','pipe')==(None,None,None)
    assert dimensions_in('2x4 in','pipe')==(None,None,None)


def test_db_branch_dimensions_flags_and_query_text(service):
    with sqlite3.connect(service.repository.path) as conn:
        conn.execute("UPDATE product_catalog SET dimensions='48x96 in', thickness_in=NULL, width_in=NULL, length_in=NULL, compliance_flags='MTR_REQUIRED' WHERE catalog_id='DEMO-SS304-060'")
    with service.repository.snapshot() as repo:
        product=repo.get_product('DEMO-SS304-060')
        assert product.thickness_in is None and product.width_in==48 and product.length_in==96
        assert product.compliance_flags=='MTR_REQUIRED'
        assert any('not verified' in w for w in product.warnings)
    service.build_index()
    sheet=json.loads((FIXTURES/'developer3_rfq.json').read_text())['items'][0]
    sheet['standard']=None
    result=service.retrieve_for_line(sheet)
    candidate=next(c for c in result.supplier_candidates if c.catalog_id=='DEMO-SS304-060')
    assert any('thickness_in unresolved' in s for s in candidate.unchecked_requirements)
    from backend.app.retrieval.adapters import adapt_line, query_text
    pipe=json.loads((FIXTURES/'developer3_rfq.json').read_text())['items'][1]
    parsed=adapt_line(pipe)
    assert '2 in SCH 40' in query_text(parsed.specification)
    assert parsed.specification.thickness.normalized_inches is None


def test_changed_sheet_width_uses_current_value_not_old_pair():
    from backend.app.retrieval.adapters import adapt_line, query_text
    line=adapt_line({'material':'SS','grade':'304','form':'sheet','dimensions':'48x96 in','width_in':24})
    text=query_text(line.specification)
    assert 'width 24 in' in text and '48x96' not in text
    assert line.specification.thickness.normalized_inches is None

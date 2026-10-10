"""Mount this router into Developer 1's FastAPI application."""
from fastapi import APIRouter, Depends
from pydantic import Field

from ..retrieval.config import create_service
from ..retrieval.models import EvidenceSet, LineEvidence, Model, RetrievalEvidence

router = APIRouter(prefix='/api/retrieval', tags=['retrieval'])


class RFQRequest(Model):
    parsed_rfq: dict
    top_k: int = Field(default=5, ge=1, le=20)


class LineRequest(Model):
    line: dict
    top_k: int = Field(default=5, ge=1, le=20)


def get_service():
    return create_service()


@router.post('/rfq', response_model=RetrievalEvidence)
def retrieve_rfq(request: RFQRequest, service=Depends(get_service)):
    return service.retrieve_for_rfq(request.parsed_rfq, request.top_k)


@router.post('/catalog', response_model=LineEvidence)
def search_catalog(request: LineRequest, service=Depends(get_service)):
    return service.search_supplier_catalog(request.line, request.top_k)


@router.get('/products/{catalog_id}/prices', response_model=EvidenceSet)
def prices(catalog_id: str, service=Depends(get_service)):
    return service.retrieve_supplier_prices(catalog_id)


@router.get('/products/{catalog_id}/history', response_model=EvidenceSet)
def history(catalog_id: str, customer_id: str | None = None, service=Depends(get_service)):
    return service.retrieve_historical_quotes(catalog_id, customer_id)


@router.get('/products/{catalog_id}/benchmarks', response_model=EvidenceSet)
def benchmarks(catalog_id: str, service=Depends(get_service)):
    return service.retrieve_market_benchmarks(catalog_id)


@router.get('/products/{catalog_id}/compliance', response_model=EvidenceSet)
def compliance(catalog_id: str, service=Depends(get_service)):
    return service.retrieve_compliance_evidence(catalog_id)

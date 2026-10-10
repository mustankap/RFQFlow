"""D2 contracts: uncertain requirements and sourced retrieval evidence."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class InputModel(Model):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)


class Thickness(InputModel):
    raw: str | None = None
    normalized_inches: float | None = Field(default=None, gt=0)
    conversion_status: str = 'unresolved'


class Dimension(InputModel):
    raw: str | None = None
    value_in: float | None = Field(default=None, gt=0)
    unit_status: str = 'unresolved'


class Specification(InputModel):
    material_family: str | None = None
    material_grade: str | None = None
    product_form: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    quantity_unit: str | None = None
    thickness: Thickness = Field(default_factory=Thickness)
    width: Dimension = Field(default_factory=Dimension)
    length: Dimension = Field(default_factory=Dimension)
    requested_standard: str | None = None
    requested_certifications: list[str] = Field(default_factory=list)
    country_of_origin_requirement: str | None = None
    finish: str | None = None


class RFQLine(InputModel):
    line_id: str = Field(min_length=1)
    original_text: str = ''
    source_reference: dict = Field(default_factory=dict)
    specification: Specification
    missing_fields: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    extraction_status: str = 'parsed'


class ParsedRFQ(InputModel):
    rfq_id: str = Field(min_length=1)
    original_text: str = ''
    customer_id: str | None = None
    items: list[RFQLine] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_id for line in self.items}) != len(self.items):
            raise ValueError('RFQ line IDs must be unique')
        return self


class Provenance(Model):
    source_id: str | None = None
    source_reference: str
    source_name: str | None = None
    source_location: str | None = None
    source_date: date | None = None
    is_synthetic: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class Product(Provenance):
    catalog_id: str
    material: str | None = None
    grade: str | None = None
    form: str | None = None
    dimensions: str | None = None
    thickness_in: float | None = Field(default=None, gt=0)
    width_in: float | None = Field(default=None, gt=0)
    length_in: float | None = Field(default=None, gt=0)
    standard: str | None = None
    description: str = ''
    compliance_flags: str | None = None


class SupplierPrice(Provenance):
    pricing_id: str
    catalog_id: str
    vendor_name: str
    cost_per_unit: Decimal = Field(ge=0)
    currency: str | None = None
    unit_of_measure: str | None = None
    lead_time_days: int | None = Field(default=None, ge=0)
    effective_date: date | None = None
    expiration_date: date | None = None
    temporal_status: Literal['current', 'expired', 'future', 'unknown'] = 'unknown'


class HistoricalQuote(Provenance):
    quote_id: str
    catalog_id: str
    customer_id: str | None = None
    customer_name: str | None = None
    raw_buyer_string: str
    final_quoted_unit_price: Decimal = Field(ge=0)
    quantity: float | None = Field(default=None, gt=0)
    currency: str | None = None
    price_unit: str | None = None
    quote_date: date | None = None
    temporal_status: Literal['historical', 'stale', 'future', 'unknown'] = 'unknown'


class Benchmark(Provenance):
    benchmark_id: str
    material: str | None = None
    grade: str | None = None
    form: str | None = None
    price: Decimal = Field(ge=0)
    currency: str | None = None
    price_unit: str | None = None
    benchmark_date: date | None = None
    size_basis: str | None = None
    region: str | None = None
    benchmark_type: str | None = None
    comparability: Literal['not_established'] = 'not_established'


class ComplianceEvidence(Provenance):
    evidence_id: str
    catalog_id: str
    document_type: str
    document_reference: str | None = None
    standard: str | None = None
    country_of_origin: str | None = None
    lot_or_heat_id: str | None = None
    verification_status: str = 'unverified'


class Candidate(Product):
    retrieval_methods: list[str]
    rank_score: float
    semantic_distance: float | None = None
    validation_status: Literal['candidate_only'] = 'candidate_only'
    potential_conflicts: list[str] = Field(default_factory=list)
    unchecked_requirements: list[str] = Field(default_factory=list)


class EvidenceSet(Model):
    supplier_prices: list[SupplierPrice] = Field(default_factory=list)
    historical_quotes: list[HistoricalQuote] = Field(default_factory=list)
    market_benchmarks: list[Benchmark] = Field(default_factory=list)
    compliance_evidence: list[ComplianceEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LineEvidence(EvidenceSet):
    line_id: str
    query_text: str
    status: Literal['ok', 'no_candidates', 'degraded', 'error']
    supplier_candidates: list[Candidate] = Field(default_factory=list)
    conflicting_candidates: list[Candidate] = Field(default_factory=list)


class RetrievalEvidence(Model):
    rfq_id: str
    session_id: str
    retrieval_method: Literal['hybrid_rrf'] = 'hybrid_rrf'
    embedding_model: str
    catalog_version: str
    distance_metric: str = 'cosine; lower is closer, not compatibility confidence'
    items: list[LineEvidence]
    warnings: list[str] = Field(default_factory=list)

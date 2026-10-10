"""Callable retrieval capabilities; no autonomous decisions or quotation pricing."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from math import isclose
from pathlib import Path

import httpx

from .adapters import adapt_line, adapt_rfq, normalize, query_text
from .models import Candidate, LineEvidence, RetrievalEvidence
from .observability import RetrievalRun
from .vector_search import IndexUnavailable


def conflicts(product, spec):
    found, unchecked = [], []
    for field, requested in [('material', spec.material_family), ('grade', spec.material_grade), ('form', spec.product_form)]:
        actual = getattr(product, field)
        if not requested or not actual:
            unchecked.append(f'{field} unresolved')
        elif normalize(actual) != normalize(requested):
            found.append(f'{field} differs: requested {requested}, catalog {actual}')
    for field, requested in [('thickness_in', spec.thickness.normalized_inches), ('width_in', spec.width.value_in), ('length_in', spec.length.value_in)]:
        actual = getattr(product, field)
        if requested is None or actual is None:
            unchecked.append(f'{field} unresolved; equivalence not established')
        elif not isclose(requested, actual, rel_tol=0, abs_tol=1e-9):
            found.append(f'{field} differs: requested {requested:g} in, catalog {actual:g} in')
    if spec.requested_standard:
        if not product.standard:
            unchecked.append('Requested standard lacks catalog evidence')
        elif normalize(spec.requested_standard) != normalize(product.standard):
            found.append(f'standard differs: requested {spec.requested_standard}, catalog {product.standard}')
    unchecked += [f'Certification {c} requires separate evidence verification' for c in spec.requested_certifications]
    if spec.country_of_origin_requirement:
        unchecked.append('Country of origin requires separate evidence verification')
    if spec.finish:
        unchecked.append('Finish has not been checked')
    if getattr(spec, 'diameter_in', None) is not None:
        unchecked.append('Diameter has not been checked')
    if getattr(spec, 'special_requirements', None):
        unchecked.append('Special requirements require separate verification')
    return found, unchecked


class RetrievalService:
    def __init__(self, repository, index, as_of: date | None = None, trace_dir: Path | None = None):
        self.repository = repository
        self.index = index
        self.as_of = as_of or datetime.now(ZoneInfo('America/New_York')).date()
        self.trace_dir = trace_dir

    def build_index(self):
        with RetrievalRun(self.trace_dir) as run, self.repository.snapshot() as repo:
            products = repo.list_products()
            result = self.index.build_index(products, repo.catalog_version(products))
            result['session_id'] = run.session_id
            result['warnings'] = run.finish(result.copy(), self.index.embedder.model)
            return result

    def _search(self, line, repo, products, version, top_k):
        spec = line.specification
        text = query_text(spec)
        warnings = [*line.ambiguities, *[f'Missing field: {f}' for f in line.missing_fields]]
        sql = repo.search_structured(spec)
        semantic = []
        status = 'ok'
        if products and any((spec.material_family, spec.material_grade, spec.product_form)):
            try:
                semantic = self.index.search_semantic(text, version, top_k=max(20, top_k*4), material=spec.material_family)
            except (IndexUnavailable, RuntimeError, ValueError, httpx.HTTPError):
                status = 'degraded'
                warnings.append('Semantic search unavailable or stale; returning structured SQLite results only')
        by_id = {p.catalog_id: p for p in products}
        assessments = {key: conflicts(p, spec) for key, p in by_id.items()}
        # Structured rank favors fewer known conflicts, then fewer unchecked fields.
        sql.sort(key=lambda p: (len(assessments[p.catalog_id][0]), len(assessments[p.catalog_id][1]), p.catalog_id))
        scores, methods, distances = {}, {}, dict(semantic)
        for method, ids in [('sql', [p.catalog_id for p in sql]), ('semantic', [key for key, _ in semantic])]:
            for rank, key in enumerate(ids, 1):
                if key not in by_id:
                    warnings.append('Vector result no longer exists in SQLite; excluded')
                    continue
                scores[key] = scores.get(key, 0) + 1/(60+rank)
                methods.setdefault(key, []).append(method)
        candidates = []
        for key in scores:
            product = by_id[key]
            found, unchecked = assessments[key]
            candidates.append(Candidate(**product.model_dump(), retrieval_methods=methods[key], rank_score=scores[key],
                semantic_distance=distances.get(key), potential_conflicts=found, unchecked_requirements=unchecked))
        candidates.sort(key=lambda c: (len(c.potential_conflicts), len(c.unchecked_requirements), -c.rank_score, c.catalog_id))
        primary = [c for c in candidates if not c.potential_conflicts][:top_k]
        conflicting = [c for c in candidates if c.potential_conflicts][:top_k]
        if not primary:
            warnings.append('No candidates without known specification conflicts; no compatible match established')
        return LineEvidence(line_id=line.line_id, query_text=text, status=status if status == 'degraded' else 'ok' if primary else 'no_candidates',
                            supplier_candidates=primary, conflicting_candidates=conflicting, warnings=warnings)

    def search_supplier_catalog(self, line, top_k=5):
        return self.retrieve_for_line(line, top_k=top_k, include_evidence=False)

    def retrieve_for_line(self, line, top_k=5, customer_id=None, include_evidence=True):
        line = adapt_line(line.model_dump() if hasattr(line, 'model_dump') else line)
        result = self.retrieve_for_rfq({'rfq_id': 'SINGLE-LINE', 'customer_id': customer_id, 'items': [line.model_dump()]}, top_k, include_evidence)
        item = result.items[0]
        item.warnings.extend(result.warnings)
        return item

    def retrieve_for_rfq(self, parsed_rfq, top_k=5, include_evidence=True):
        if not 1 <= top_k <= 20:
            raise ValueError('top_k must be between 1 and 20')
        rfq = adapt_rfq(parsed_rfq)
        with RetrievalRun(self.trace_dir) as run, self.repository.snapshot() as repo:
            products = repo.list_products()
            version = repo.catalog_version(products)
            items = []
            for line in rfq.items:
                item = self._search(line, repo, products, version, top_k)
                if include_evidence:
                    for candidate in item.supplier_candidates:
                        for kind in ('supplier_prices', 'historical_quotes', 'market_benchmarks', 'compliance_evidence'):
                            evidence = repo.evidence(candidate.catalog_id, kind, self.as_of, rfq.customer_id)
                            getattr(item, kind).extend(getattr(evidence, kind))
                            item.warnings.extend(evidence.warnings)
                    for quote in item.historical_quotes:
                        if quote.quantity is not None and line.specification.quantity is not None and quote.quantity != line.specification.quantity:
                            quote.warnings.append('Historical quantity differs from this request; price comparability unresolved')
                    # Benchmarks can be shared across multiple catalog candidates.
                    for field, key in [('supplier_prices','pricing_id'), ('historical_quotes','quote_id'),
                                       ('market_benchmarks','benchmark_id'), ('compliance_evidence','evidence_id')]:
                        setattr(item, field, list({getattr(r,key): r for r in getattr(item,field)}.values()))
                    if any(c.upper() == 'MTR' for c in line.specification.requested_certifications):
                        mtrs = [e for e in item.compliance_evidence if e.document_type.upper() == 'MTR']
                        if not mtrs:
                            item.warnings.append('Requested MTR evidence is missing')
                        else:
                            item.warnings.append('MTR records retrieved; verification and lot applicability remain unresolved')
                item.warnings = list(dict.fromkeys(item.warnings))
                items.append(item)
            result = RetrievalEvidence(rfq_id=rfq.rfq_id, session_id=run.session_id,
                embedding_model=self.index.embedder.model, catalog_version=version, items=items)
            result.warnings = run.finish(result.model_dump(mode='json'), self.index.embedder.model)
            return result

    def _evidence(self, catalog_id, kind, customer_id=None):
        with RetrievalRun(self.trace_dir) as run, self.repository.snapshot() as repo:
            evidence = repo.evidence(catalog_id, kind, self.as_of, customer_id)
            evidence.warnings.extend(run.finish({'tool': kind, **evidence.model_dump(mode='json')}, self.index.embedder.model))
            return evidence

    def retrieve_supplier_prices(self, catalog_id):
        return self._evidence(catalog_id, 'supplier_prices')

    def retrieve_historical_quotes(self, catalog_id, customer_id=None):
        return self._evidence(catalog_id, 'historical_quotes', customer_id)

    def retrieve_market_benchmarks(self, catalog_id):
        return self._evidence(catalog_id, 'market_benchmarks')

    def retrieve_compliance_evidence(self, catalog_id):
        return self._evidence(catalog_id, 'compliance_evidence')

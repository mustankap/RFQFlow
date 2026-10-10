"""Labeled fixture evaluation, not an LLM-generated quality score."""
import json
from pathlib import Path


def evaluate(service, cases_path: Path):
    cases = json.loads(cases_path.read_text())
    rows = []
    for case in cases:
        evidence = service.retrieve_for_rfq(case['rfq'], top_k=5)
        line = evidence.items[0]
        ids = [p.catalog_id for p in line.supplier_candidates]
        relevant = set(case['relevant_catalog_ids'])
        recalls = {f'recall_at_{k}': len(relevant.intersection(ids[:k])) / len(relevant) if relevant else None for k in (3,5)}
        passed = (bool(relevant) and recalls['recall_at_5'] == 1) or (not relevant and not ids)
        if case.get('warning_contains'):
            passed = passed and any(case['warning_contains'] in w for w in line.warnings)
        conflicts_flagged = all(c.potential_conflicts for c in line.conflicting_candidates)
        provenance = all(c.source_reference and c.source_id and c.is_synthetic is True for c in line.supplier_candidates + line.conflicting_candidates)
        rows.append({'case_id': case['case_id'], **recalls, 'retrieved_ids': ids, 'expected_ids': sorted(relevant),
                     'status': line.status, 'passed': bool(passed and conflicts_flagged and provenance and line.status != 'degraded'),
                     'conflicts_flagged': conflicts_flagged, 'fixture_provenance_complete': provenance,
                     'session_id': evidence.session_id})
    summary = {'cases': len(rows), 'passed': sum(r['passed'] for r in rows),
               'model': service.index.embedder.model,
               'scope': 'Bundled synthetic fixtures only; no general accuracy claim', 'results': rows}
    for k in (3,5):
        values = [r[f'recall_at_{k}'] for r in rows if r[f'recall_at_{k}'] is not None]
        summary[f'mean_recall_at_{k}'] = sum(values)/len(values) if values else None
    return summary


def export_grounding(repository, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with repository.snapshot() as repo:
        products = repo.list_products()
        content = '\n\n'.join(
            f'Catalog ID: {p.catalog_id}\nMaterial: {p.material}\nGrade: {p.grade}\nForm: {p.form}\n'
            f'Dimensions: {p.dimensions}\nSource ID: {p.source_id}\nSource reference: {p.source_reference}\n'
            f'Synthetic: {p.is_synthetic}\nNo compliance or current pricing approval is established.' for p in products)
    (directory/'catalog-grounding.txt').write_text(content + '\n')
    return {'documents': len(products), 'path': str(directory/'catalog-grounding.txt'),
            'status': 'exported_for_PRISM_Knowledge_Base; not uploaded or grounded yet'}

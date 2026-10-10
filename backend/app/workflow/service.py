"""Small synchronous demo workflow. Sessions last until server restart."""
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from threading import RLock
from math import isclose

from backend.app.ingestion.parser import parse_rfq_text, normalize_thickness
from backend.app.retrieval.embeddings import NicrronEmbeddings
from backend.app.retrieval.vector_search import RetrievalIndex, load_products
from backend.app.retrieval.models import ParsedRFQ

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'backend/data/fixtures/retrieval'


def money(value):
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


class QuoteWorkflow:
    def __init__(self, parser=parse_rfq_text, retriever=None):
        self.parser = parser
        self.retriever = retriever
        self.sessions = {}
        self.lock = RLock()
        self.catalog = {p.sku: p for p in load_products(DATA / 'supplier_catalog.json').products}
        self.prices = json.loads((DATA / 'demo_prices.json').read_text())

    def run(self, text):
        return self.run_parsed(self.parser(text))

    def run_parsed(self, rfq: ParsedRFQ):
        rfq = ParsedRFQ.model_validate(rfq.model_dump()).model_copy(deep=True)
        with self.lock:
            self.sessions[rfq.rfq_id] = {'rfq': rfq, 'answers': [], 'revision': 1}
            return self.evaluate(self.sessions[rfq.rfq_id])

    def clarify(self, rfq_id, answers):
        with self.lock:
            if rfq_id not in self.sessions:
                raise KeyError(rfq_id)
            state = self.sessions[rfq_id]
            rfq = state['rfq'].model_copy(deep=True)
            for answer in answers:
                line = next((i for i in rfq.items if i.line_id == answer.line_id), None)
                if line is None:
                    raise ValueError('Unknown line_id')
                spec = line.specification
                field, value = answer.field, answer.value.strip()
                if not value:
                    raise ValueError('Answer cannot be empty')
                if field in ('thickness', 'width', 'length'):
                    # Single explicit measurement; gauge and bare numbers stay unresolved.
                    inches, status, warning = normalize_thickness(value, value)
                    if field == 'thickness':
                        spec.thickness.raw = value
                        spec.thickness.normalized_inches = inches
                        spec.thickness.conversion_status = status
                    else:
                        dim = getattr(spec, field)
                        dim.raw, dim.value_in, dim.unit_status = value, inches, status
                elif field == 'quantity':
                    quantity = Decimal(value)
                    if not quantity.is_finite() or quantity <= 0:
                        raise ValueError('Quantity must be finite and positive')
                    spec.quantity = float(quantity)
                else:
                    setattr(spec, field, value)
            rfq = ParsedRFQ.model_validate(rfq.model_dump())
            state['rfq'] = rfq
            state['answers'].extend(a.model_dump() for a in answers)
            state['revision'] += 1
            return self.evaluate(state)

    def evaluate(self, state):
        rfq = state['rfq']
        questions, outputs, quote_lines = [], [], []
        blockers = list(getattr(rfq, 'errors', []))
        unresolved_segments = getattr(rfq, 'unparsed_segments', [])
        if unresolved_segments:
            blockers.append('Source segments remain unaccounted for')
        ready_lines = []
        for line in rfq.items:
            s = line.specification
            missing = [name for name in ('material_family','material_grade','product_form','quantity','quantity_unit') if not getattr(s,name)]
            if s.thickness.normalized_inches is None or s.thickness.conversion_status not in ('explicit','verified_from_explicit_units'):
                missing.append('thickness')
            for name in ('width','length'):
                d = getattr(s,name)
                if d.value_in is None or d.unit_status not in ('explicit','verified_from_explicit_units'):
                    missing.append(name)
            if s.quantity_unit and s.quantity_unit.lower() not in ('pcs','piece','pieces'):
                missing.append('quantity_unit')
            if s.product_form and s.product_form not in ('sheet','plate'):
                missing.append('product_form')
            line.missing_fields = list(dict.fromkeys(missing))
            line.extraction_status = 'needs_review' if missing else 'extracted'
            for field in line.missing_fields:
                prompt = f'Please confirm {field.replace("_", " ")} for {line.line_id}.'
                if field in ('thickness','width','length'):
                    prompt += ' Provide a numeric measurement with explicit in or mm units; gauge requires verified decimal thickness.'
                questions.append({'line_id':line.line_id,'field':field,'question':prompt})
            outputs.append({'line_id':line.line_id,'source_reference':line.source_reference,'missing_fields':line.missing_fields,'supplier_candidates':[], 'selected_product':None,'pricing':None,'compliance':{'status':'UNVERIFIED','checks':[]},'blockers':[],'status':'NEEDS_CLARIFICATION' if missing else 'EXTRACTED'})
            if missing:
                outputs[-1]['blockers'].append('Unresolved specification')
            else:
                ready_lines.append(line)
        if ready_lines:
            subset = rfq.model_copy(update={'items':ready_lines})
            retriever = self.retriever or RetrievalIndex(Path(os.getenv('CHROMA_PATH', str(ROOT / '.local/chroma'))), NicrronEmbeddings())
            evidence = retriever.retrieve_for_rfq(subset)
            by_id = {x['line_id']:x for x in evidence['items']}
            for line in ready_lines:
                out = next(x for x in outputs if x['line_id']==line.line_id)
                candidates = by_id[line.line_id]['supplier_candidates']
                out['supplier_candidates'] = candidates
                selected = None
                s = line.specification
                for c in candidates:
                    p = self.catalog.get(c['sku'])
                    if p and all(getattr(p,k)==getattr(s,k) for k in ('material_family','material_grade','product_form')) and all(isclose(v,getattr(p,k),rel_tol=0,abs_tol=1e-9) for k,v in [('thickness_in',s.thickness.normalized_inches),('width_in',s.width.value_in),('length_in',s.length.value_in)]):
                        selected = p
                        break
                if selected is None:
                    out['blockers'].append('No compatible catalog product')
                    continue
                out['selected_product'] = selected.model_dump()
                out['status'] = 'MATCHED'
                requirements = []
                # A missed extraction must not erase a source compliance requirement.
                source = rfq.original_text
                requirements.extend(('standard',v) for v in re.findall(r'\bASTM\s+[A-Z]\s*\d+(?:/\w+)?',source,re.I))
                if re.search(r'\bMTRs?\b|mill test reports?',source,re.I):
                    requirements.append(('certification','MTR'))
                if re.search(r'country of origin|\b(?:USA|US|domestic)[ -]?(?:made|origin)|made in',source,re.I):
                    requirements.append(('country_of_origin','Buyer origin requirement requires evidence'))
                if getattr(s,'requested_standard',None): requirements.append(('standard',s.requested_standard))
                requirements.extend(('certification',c) for c in getattr(s,'requested_certifications',[]))
                if getattr(s,'country_of_origin_requirement',None): requirements.append(('country_of_origin',s.country_of_origin_requirement))
                out['compliance'] = {'status':'UNVERIFIED' if requirements else 'NOT_REQUIRED','checks':[{'type':k,'requested':v,'status':'UNVERIFIED','evidence':None} for k,v in requirements]}
                if requirements:
                    out['blockers'].append('Required compliance evidence unavailable')
                cost = self.prices['costs'].get(selected.sku)
                if cost is None:
                    out['blockers'].append('Supplier cost unavailable')
                    continue
                unit = (Decimal(cost)*(1+Decimal(self.prices['markup_percent'])/100)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                total = (unit*Decimal(str(s.quantity))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                out['pricing'] = {'label':'DEMO DATA','is_synthetic':True,'currency':'USD','price_unit':'pieces','supplier_unit_cost':cost,'markup_percent':self.prices['markup_percent'],'unit_selling_price':money(unit),'line_total':money(total),'source_id':f'SYNTH-PRICE-{selected.sku}','market_assessment':'Market competitiveness not established.'}
                if not out['blockers']:
                    out['status']='QUOTE_READY'
                    quote_lines.append({'line_id':line.line_id,'sku':selected.sku,'quantity':s.quantity,'source_reference':line.source_reference,'catalog_source_id':selected.source_id,**out['pricing']})
        blockers.extend(f"{o['line_id']}: {b}" for o in outputs for b in o['blockers'])
        ready = not blockers and len(quote_lines)==len(rfq.items)
        subtotal = sum((Decimal(l['line_total']) for l in quote_lines),Decimal(0))
        final = {'label':'DEMO DATA — synthetic quotation','currency':'USD','lines':quote_lines,'subtotal':money(subtotal),'additional_charges':'0.00','grand_total':money(subtotal),'terms':'Demo only; freight and tax excluded; availability and delivery not established.','market_assessment':'Market competitiveness not established.'} if ready else None
        return {'rfq_id':rfq.rfq_id,'revision':state['revision'],'parsed_rfq':rfq.model_dump(),'buyer_answers':state['answers'],'clarification_questions':questions,'items':outputs,'blockers':blockers,'overall_status':'QUOTE_READY' if ready else ('NEEDS_CLARIFICATION' if questions else 'BLOCKED'),'final_quotation':final,'market_assessment':'Market competitiveness not established.'}

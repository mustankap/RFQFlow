"""Reconcile the nested contract and the team's simplified flat RFQ lines."""
import re
from fractions import Fraction

from .models import ParsedRFQ, RFQLine, Specification

ALIASES = {'ss': 'stainless steel', 'stainless': 'stainless steel', 'steel': 'carbon steel',
           'aluminium': 'aluminum', 'al': 'aluminum'}


def normalize(value):
    if value is None:
        return None
    value = ' '.join(str(value).lower().split())
    return ALIASES.get(value, value) or None


def dimensions_in(raw: str | None) -> tuple[float | None, float | None, float | None]:
    """Only explicit thickness x width x length with one shared unit is supported.

    '1/4 x 48 x 96 in' is explicit; '16ga 4x8' and mixed units remain unresolved.
    No industrial convention or gauge equivalence is inferred.
    """
    if not raw:
        return None, None, None
    number = r'(\d+(?:\.\d+)?(?:/\d+)?)'
    match = re.fullmatch(rf'\s*{number}\s*[x×]\s*{number}\s*[x×]\s*{number}\s*(inches|inch|in|mm|ft|feet|")\s*', raw, re.I)
    if not match:
        return None, None, None
    try:
        factor = {'mm': 1/25.4, 'ft': 12, 'feet': 12}.get(match[4].lower(), 1)
        values = tuple(float(Fraction(match[i])) * factor for i in (1, 2, 3))
        return values if all(v > 0 for v in values) else (None, None, None)
    except (ValueError, ZeroDivisionError):
        return None, None, None


def adapt_line(data: dict, line_id: str | None = None) -> RFQLine:
    if not isinstance(data, dict):
        raise ValueError('Each RFQ line must be a JSON object')
    if 'specification' in data:
        line = RFQLine.model_validate(data)
    else:
        dims = dimensions_in(data.get('dimensions'))
        standard = data.get('standard')
        ambiguous = list(data.get('ambiguities', []))
        if standard and standard.strip().upper() == 'ASTM':
            standard = None
            ambiguous.append('Generic ASTM label is not a specified technical standard')
        line = RFQLine(
            line_id=data.get('line_id') or line_id or 'LINE-001',
            original_text=data.get('raw_input', data.get('original_text', '')),
            source_reference=data.get('source_reference', {}),
            specification=Specification(
                material_family=data.get('material'), material_grade=data.get('grade'),
                product_form=data.get('form'), quantity=data.get('quantity'),
                quantity_unit=data.get('quantity_unit'),
                thickness={'raw': data.get('dimensions'), 'normalized_inches': data.get('thickness_in', dims[0]),
                           'conversion_status': 'explicit' if data.get('thickness_in', dims[0]) is not None else 'unresolved'},
                width={'raw': data.get('dimensions'), 'value_in': data.get('width_in', dims[1]),
                       'unit_status': 'explicit' if data.get('width_in', dims[1]) is not None else 'unresolved'},
                length={'raw': data.get('dimensions'), 'value_in': data.get('length_in', dims[2]),
                        'unit_status': 'explicit' if data.get('length_in', dims[2]) is not None else 'unresolved'},
                requested_standard=standard,
                requested_certifications=data.get('requested_certifications', []) + (['MTR'] if data.get('requires_mtr') else []),
                country_of_origin_requirement=data.get('country_of_origin_requirement'), finish=data.get('finish'),
            ), ambiguities=ambiguous, missing_fields=data.get('missing_fields', []),
        )
    spec = line.specification
    if spec.requested_standard and spec.requested_standard.strip().upper() == 'ASTM':
        spec.requested_standard = None
        line.ambiguities.append('Generic ASTM label is not a specified technical standard')
    spec.material_family = normalize(spec.material_family)
    spec.material_grade = normalize(spec.material_grade)
    spec.product_form = normalize(spec.product_form)
    # An inferred or unresolved value must not become a verified search constraint.
    if spec.thickness.conversion_status not in {'explicit', 'converted', 'verified'}:
        spec.thickness.normalized_inches = None
    for name in ('width', 'length'):
        dim = getattr(spec, name)
        if dim.unit_status not in {'explicit', 'converted', 'verified'}:
            dim.value_in = None
    for name in ('material_family', 'material_grade', 'product_form', 'quantity', 'quantity_unit'):
        if getattr(spec, name) is None and name not in line.missing_fields:
            line.missing_fields.append(name)
    return line


def adapt_rfq(data: dict | ParsedRFQ) -> ParsedRFQ:
    data = data.model_dump() if isinstance(data, ParsedRFQ) else dict(data)
    if 'items' not in data:
        data = {'rfq_id': data.get('rfq_id', 'RFQ-001'), 'items': [data]}
    if not isinstance(data['items'], list) or not 1 <= len(data['items']) <= 100:
        raise ValueError('RFQ items must contain between 1 and 100 line objects')
    data['items'] = [adapt_line(row, f'LINE-{i:03}').model_dump() for i, row in enumerate(data['items'], 1)]
    return ParsedRFQ.model_validate(data)


def query_text(spec: Specification) -> str:
    parts = [spec.material_family, spec.material_grade, spec.product_form]
    for label, value in [('thickness', spec.thickness.normalized_inches), ('width', spec.width.value_in), ('length', spec.length.value_in)]:
        if value is not None:
            parts.append(f'{label} {value:g} in')
    if spec.requested_standard:
        parts.append(spec.requested_standard)
    return '; '.join(p for p in parts if p) or 'unspecified material request'

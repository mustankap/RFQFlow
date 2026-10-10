"""Read-only adapter for Developer 3's SQLite table names.

Extra evidence columns/tables are optional. Their absence is reported, never
filled with invented provenance, currencies, or certification claims.
"""
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from .adapters import ALIASES, dimensions_in, normalize
from .models import Benchmark, ComplianceEvidence, EvidenceSet, HistoricalQuote, Product, SupplierPrice


class SQLiteRepository:
    def __init__(self, path: Path, connection=None):
        self.path = Path(path).resolve()
        self.connection = connection

    @contextmanager
    def snapshot(self):
        if self.connection is not None:
            yield self
            return
        if not self.path.is_file():
            raise FileNotFoundError('SQLite database is missing; run seed-demo or configure RFQ_SQLITE_PATH')
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            try:
                yield SQLiteRepository(self.path, conn)
            finally:
                conn.rollback()

    def _tables(self):
        return {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def _rows(self, table, where='', params=()):
        # Table names/WHERE fragments come only from this module, values are bound.
        if table not in self._tables():
            return []
        return [dict(r) for r in self.connection.execute(f'SELECT * FROM {table} {where}', params)]

    @staticmethod
    def _date(value, warnings, field):
        if not value:
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            warnings.append(f'Invalid {field}; date unresolved')
            return None

    def _provenance(self, row, table, key):
        warnings = []
        source_id = row.get('source_id')
        source = {}
        if source_id and 'source_documents' in self._tables():
            sources = self._rows('source_documents', 'WHERE source_id = ?', (source_id,))
            source = sources[0] if sources else {}
            if not source:
                warnings.append('Source ID has no matching source document')
        if not source_id:
            warnings.append('Original source metadata unavailable; only database row provenance exists')
        synthetic = row.get('is_synthetic')
        if synthetic is None:
            synthetic = source.get('is_synthetic')
        if synthetic not in (0, 1, None):
            warnings.append('Invalid synthetic flag; data origin unknown')
            synthetic = None
        if synthetic is None:
            warnings.append('Synthetic/real data origin is unknown')
        return dict(source_id=source_id, source_name=source.get('source_name'), source_location=source.get('source_location'),
                    source_reference=f'sqlite:{self.path.name}/{table}/{key}',
                    source_date=self._date(row.get('source_date') or source.get('effective_date'), warnings, 'source_date'),
                    is_synthetic=bool(synthetic) if synthetic is not None else None, warnings=warnings)

    def _product(self, row):
        provenance = self._provenance(row, 'product_catalog', row['catalog_id'])
        dims = dimensions_in(row.get('dimensions'))
        numbers = [row.get(name) if row.get(name) is not None else dims[i]
                   for i, name in enumerate(('thickness_in', 'width_in', 'length_in'))]
        if any(v is None for v in numbers):
            provenance['warnings'].append('Catalog dimensions are incomplete or have unresolved units')
        standard = row.get('standard')
        if standard and standard.strip().upper() == 'ASTM':
            standard = None
            provenance['warnings'].append('Generic ASTM label is not a specific standard')
        return Product(**provenance, catalog_id=row['catalog_id'], material=normalize(row.get('material')),
                       grade=normalize(row.get('grade')), form=normalize(row.get('form')),
                       dimensions=row.get('dimensions'), thickness_in=numbers[0], width_in=numbers[1], length_in=numbers[2],
                       standard=standard, description=row.get('description') or '')

    def list_products(self):
        if 'product_catalog' not in self._tables():
            raise ValueError('SQLite must contain Developer 3 product_catalog table')
        products = [self._product(r) for r in self._rows('product_catalog', 'ORDER BY catalog_id')]
        return products

    def get_product(self, catalog_id):
        rows = self._rows('product_catalog', 'WHERE catalog_id = ?', (catalog_id,))
        return self._product(rows[0]) if rows else None

    def search_structured(self, specification):
        clauses, params = [], []
        for column, value in [('material', specification.material_family), ('grade', specification.material_grade),
                              ('form', specification.product_form)]:
            if value:
                aliases = sorted({normalize(value), *[k for k, v in ALIASES.items() if v == normalize(value)]})
                clauses.append(f'lower(trim({column})) IN ({",".join("?" for _ in aliases)})')
                params.extend(aliases)
        if not clauses:
            return []
        rows = self._rows('product_catalog', 'WHERE ' + ' AND '.join(clauses) + ' ORDER BY catalog_id', params)
        return [self._product(row) for row in rows]

    @staticmethod
    def catalog_version(products):
        content = json.dumps([p.model_dump(mode='json') for p in products], sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _money(value, warnings):
        if isinstance(value, float):
            warnings.append('Legacy SQLite REAL price converted to Decimal; original rounding precision is unknown')
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Price must be finite and non-negative')
        return amount

    def evidence(self, catalog_id, kind, as_of: date, customer_id=None, stale_days=90):
        config = {
            'supplier_prices': ('vendor_pricing', 'catalog_id', 'pricing_id'),
            'historical_quotes': ('historical_quotes', 'matched_catalog_id', 'quote_id'),
            'compliance_evidence': ('compliance_documents', 'catalog_id', 'evidence_id'),
            'market_benchmarks': ('market_benchmarks', None, 'benchmark_id'),
        }
        table, foreign_key, key = config[kind]
        output = EvidenceSet()
        if not self.get_product(catalog_id):
            output.warnings.append(f'Unknown catalog ID: {catalog_id}')
            return output
        if table not in self._tables():
            output.warnings.append(f'{kind}: table unavailable in SQLite')
            return output
        rows = self._rows(table, f'WHERE {foreign_key} = ?' if foreign_key else '', (catalog_id,) if foreign_key else ())
        for row in rows:
            provenance = self._provenance(row, table, row[key])
            warnings = provenance['warnings']
            try:
                if kind == 'supplier_prices':
                    effective = self._date(row.get('effective_date'), warnings, 'effective_date')
                    expires = self._date(row.get('expiration_date'), warnings, 'expiration_date')
                    status = 'expired' if expires and expires < as_of else 'future' if effective and effective > as_of else 'current' if effective and expires else 'unknown'
                    if status != 'current':
                        warnings.append(f'Supplier price validity: {status}')
                    if effective and expires and expires < effective:
                        status = 'unknown'
                        warnings.append('Expiration precedes effective date')
                    for field in ('currency', 'unit_of_measure'):
                        if not row.get(field):
                            warnings.append(f'Missing {field}; price comparison unresolved')
                    record = SupplierPrice(**provenance, pricing_id=str(row[key]), catalog_id=catalog_id,
                        vendor_name=row['vendor_name'], cost_per_unit=self._money(row['cost_per_unit'], warnings),
                        currency=row.get('currency'), unit_of_measure=row.get('unit_of_measure'),
                        lead_time_days=row.get('lead_time_days'), effective_date=effective,
                        expiration_date=expires, temporal_status=status)
                elif kind == 'historical_quotes':
                    # Explicit customer scope never falls back to a different customer.
                    if customer_id and row.get('customer_id') != customer_id:
                        continue
                    quoted = self._date(row.get('quote_date'), warnings, 'quote_date')
                    status = 'unknown' if not quoted else 'future' if quoted > as_of else 'stale' if (as_of-quoted).days > stale_days else 'historical'
                    warnings.append('Historical customer quote is not current supplier cost or an approved selling price')
                    if not customer_id:
                        warnings.append('Cross-customer reference only; customer-specific pricing may not apply')
                    if status != 'historical':
                        warnings.append(f'Quote date status: {status}')
                    for field in ('quantity', 'currency', 'price_unit'):
                        if not row.get(field):
                            warnings.append(f'Missing historical {field}')
                    record = HistoricalQuote(**provenance, quote_id=row[key], catalog_id=catalog_id,
                        customer_id=row.get('customer_id'), customer_name=row.get('customer_name'),
                        raw_buyer_string=row.get('raw_buyer_string') or '',
                        final_quoted_unit_price=self._money(row['final_quoted_unit_price'], warnings),
                        quantity=row.get('quantity'), currency=row.get('currency'), price_unit=row.get('price_unit'),
                        quote_date=quoted, temporal_status=status)
                elif kind == 'compliance_evidence':
                    warnings.append('Document metadata is evidence only; lot applicability and compliance require separate verification')
                    if not row.get('document_reference'):
                        warnings.append('Supporting document reference missing')
                    record = ComplianceEvidence(**provenance, evidence_id=row[key], catalog_id=catalog_id,
                        document_type=row['document_type'], document_reference=row.get('document_reference'),
                        standard=row.get('standard'), country_of_origin=row.get('country_of_origin'),
                        lot_or_heat_id=row.get('lot_or_heat_id'), verification_status=row.get('verification_status') or 'unverified')
                else:
                    product = self.get_product(catalog_id)
                    if any(row.get(f) and normalize(row[f]) != getattr(product, f) for f in ('material', 'grade', 'form')):
                        continue
                    warnings.append('Benchmark commercial comparability is not established; do not infer market competitiveness')
                    if row.get('benchmark_type') == 'surcharge':
                        warnings.append('Surcharge is not a finished-product price')
                    record = Benchmark(**provenance, benchmark_id=row[key], material=row.get('material'),
                        grade=row.get('grade'), form=row.get('form'), price=self._money(row['price'], warnings),
                        currency=row.get('currency'), price_unit=row.get('price_unit'),
                        benchmark_date=self._date(row.get('benchmark_date'), warnings, 'benchmark_date'),
                        region=row.get('region'), size_basis=row.get('size_basis'), benchmark_type=row.get('benchmark_type'))
                # Capture warnings appended while evaluating constructor arguments.
                if kind == 'market_benchmarks':
                    if record.benchmark_date is None:
                        warnings.append('Benchmark date unavailable')
                    elif record.benchmark_date > as_of:
                        warnings.append('Benchmark is dated in the future')
                    elif (as_of-record.benchmark_date).days > stale_days:
                        warnings.append('Benchmark is stale under the configured age policy')
                    for field in ('currency', 'price_unit', 'size_basis', 'region'):
                        if not getattr(record, field):
                            warnings.append(f'Missing benchmark {field}; comparability unresolved')
                record.warnings = list(warnings)
                getattr(output, kind).append(record)
            except (ValueError, TypeError, KeyError, InvalidOperation, ValidationError):
                output.warnings.append(f'Invalid {table} record {row.get(key)} excluded; inspect canonical data')
        if kind == 'historical_quotes':
            output.historical_quotes.sort(key=lambda r: (r.quote_date or date.min, r.quote_id), reverse=True)
        if not getattr(output, kind):
            output.warnings.append(f'No {kind} available for {catalog_id} in the requested scope')
        return output

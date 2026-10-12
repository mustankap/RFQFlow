"""Explicitly synthetic D2 fixture database; never migrates Developer 3's DB."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE source_documents (source_id TEXT PRIMARY KEY, source_name TEXT NOT NULL,
 source_location TEXT NOT NULL, effective_date TEXT, is_synthetic INTEGER NOT NULL CHECK(is_synthetic IN (0,1)));
CREATE TABLE product_catalog (
 catalog_id TEXT PRIMARY KEY, material TEXT NOT NULL, grade TEXT NOT NULL, form TEXT NOT NULL,
 dimensions TEXT NOT NULL, standard TEXT, compliance_flags TEXT,
 thickness_in REAL CHECK(thickness_in>0), width_in REAL CHECK(width_in>0), length_in REAL CHECK(length_in>0),
 description TEXT, source_id TEXT REFERENCES source_documents(source_id), source_date TEXT,
 is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE TABLE vendor_pricing (
 pricing_id INTEGER PRIMARY KEY AUTOINCREMENT, catalog_id TEXT NOT NULL REFERENCES product_catalog(catalog_id),
 vendor_name TEXT NOT NULL, cost_per_unit TEXT NOT NULL, unit_of_measure TEXT NOT NULL,
 lead_time_days INTEGER NOT NULL CHECK(lead_time_days>=0), currency TEXT,
 effective_date TEXT, expiration_date TEXT, source_id TEXT REFERENCES source_documents(source_id), is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE TABLE historical_quotes (
 quote_id TEXT PRIMARY KEY, customer_name TEXT NOT NULL, raw_buyer_string TEXT NOT NULL,
 matched_catalog_id TEXT NOT NULL REFERENCES product_catalog(catalog_id), final_quoted_unit_price TEXT NOT NULL,
 compliance_verified TEXT NOT NULL, quote_date TEXT NOT NULL, customer_id TEXT,
 quantity REAL CHECK(quantity>0), currency TEXT, price_unit TEXT,
 source_id TEXT REFERENCES source_documents(source_id), is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE TABLE market_benchmarks (
 benchmark_id TEXT PRIMARY KEY, material TEXT, grade TEXT, form TEXT, price TEXT NOT NULL,
 currency TEXT, price_unit TEXT, benchmark_date TEXT, size_basis TEXT, region TEXT, benchmark_type TEXT,
 source_id TEXT REFERENCES source_documents(source_id), is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE TABLE compliance_documents (
 evidence_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL REFERENCES product_catalog(catalog_id), document_type TEXT NOT NULL,
 document_reference TEXT, standard TEXT, country_of_origin TEXT, lot_or_heat_id TEXT, verification_status TEXT,
 source_id TEXT REFERENCES source_documents(source_id), is_synthetic INTEGER NOT NULL CHECK(is_synthetic=1));
CREATE INDEX catalog_specs ON product_catalog(material, grade, form);
CREATE INDEX vendor_catalog ON vendor_pricing(catalog_id);
CREATE INDEX history_catalog ON historical_quotes(matched_catalog_id, customer_id, quote_date);
CREATE INDEX compliance_catalog ON compliance_documents(catalog_id);
'''


def seed_demo(path: Path, fixture: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive file creation prevents accidental replacement of a canonical DB.
    path.touch(exist_ok=False)
    try:
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript(SCHEMA)
            products = json.loads(fixture.read_text())['products']
            for p in products:
                conn.execute('INSERT INTO source_documents VALUES (?,?,?,?,1)',
                    (p['source_id'], 'Fictional catalog fixture', 'backend/data/fixtures/retrieval/supplier_catalog.json', '2026-10-10'))
                conn.execute('INSERT INTO product_catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                    (p['sku'], p['material_family'], p['material_grade'], p['product_form'],
                     f"{p['thickness_in']} x {p['width_in']} x {p['length_in']} in", None, None,
                     p['thickness_in'], p['width_in'], p['length_in'], p['description'], p['source_id'], p['source_date']))
            conn.execute('INSERT INTO source_documents VALUES (?,?,?,?,1)',
                         ('SYNTH-EVIDENCE', 'Fictional evidence fixture', 'backend/app/retrieval/demo.py', '2026-10-01'))
            for product, vendor, cost, lead in [('DEMO-SS304-060', 'Fictional Vendor A', '100.00', 5),
                                              ('DEMO-SS304-060', 'Fictional Vendor B', '103.25', 2),
                                              ('DEMO-AL6061-250', 'Fictional Vendor A', '75.00', 7)]:
                conn.execute('''INSERT INTO vendor_pricing (catalog_id,vendor_name,cost_per_unit,unit_of_measure,
                    lead_time_days,currency,effective_date,expiration_date,source_id,is_synthetic)
                    VALUES (?,?,?,'per_piece',?,'USD','2026-10-01','2026-10-31','SYNTH-EVIDENCE',1)''', (product,vendor,cost,lead))
            for qid, customer, date, price in [('SYNTH-H1','CUST-A','2026-09-15','125.00'),
                                            ('SYNTH-H2','CUST-B','2025-01-01','110.00')]:
                conn.execute('INSERT INTO historical_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)',
                    (qid,'Fictional '+customer,'304 stainless steel sheet','DEMO-SS304-060',price,
                     'unverified',date,customer,20,'USD','per_piece','SYNTH-EVIDENCE'))
            conn.execute("INSERT INTO market_benchmarks VALUES ('SYNTH-B1','stainless steel','304','sheet','1.25','USD','per_lb','2026-10-01','mill surcharge','US','surcharge','SYNTH-EVIDENCE',1)")
            conn.execute("INSERT INTO compliance_documents VALUES ('SYNTH-C1','DEMO-SS304-060','catalog_specification','synthetic://catalog/ss304',NULL,NULL,NULL,'unverified','SYNTH-EVIDENCE',1)")
            conn.execute("INSERT INTO compliance_documents VALUES ('SYNTH-C2','DEMO-AL6061-250','MTR','synthetic://mtr/example-not-real',NULL,'US','SYNTH-HEAT-001','synthetic_unverified','SYNTH-EVIDENCE',1)")
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Invalid fixture foreign keys')
    except Exception:
        path.unlink(missing_ok=True)
        raise

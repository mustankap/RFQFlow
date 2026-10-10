import os
import sqlite3
import json
import pandas as pd
import chromadb
from pydantic import BaseModel
from typing import Optional

# Define workspace local footprints
DB_PATH = "data/rudco_internal.db"
VECTOR_PATH = "data/chroma_vector_storage"
os.makedirs("data", exist_ok=True)

# =====================================================================
# 1. SPECIFICATION & INBOUND SCHEMAS (Pydantic / FastAPI Layer)
# =====================================================================
class ParsedRFQLine(BaseModel):
    raw_input: str
    material: str
    grade: str
    form: str
    dimensions: str
    quantity: int
    standard: Optional[str] = "ASTM"

# =====================================================================
# 2. SEED STORAGE LAYOUT INITIALIZATION (SQLite)
# =====================================================================
def init_storage_layers():
    """Initializes isolated structural tables matching regional logistics data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Material catalog configuration index
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_catalog (
        catalog_id TEXT PRIMARY KEY,
        material TEXT NOT NULL,
        grade TEXT NOT NULL,
        form TEXT NOT NULL,
        dimensions TEXT NOT NULL,
        standard TEXT NOT NULL,
        compliance_flags TEXT
    )
    """)
    
    # Multi-vendor pricing registry (Handles delivery timelines and variable base unit costs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendor_pricing (
        pricing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id TEXT,
        vendor_name TEXT NOT NULL,
        cost_per_unit REAL NOT NULL,
        unit_of_measure TEXT NOT NULL,
        lead_time_days INTEGER NOT NULL,
        FOREIGN KEY(catalog_id) REFERENCES product_catalog(catalog_id)
    )
    """)
    
    # Historical pipeline tracking matching customer orders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historical_quotes (
        quote_id TEXT PRIMARY KEY,
        customer_name TEXT NOT NULL,
        raw_buyer_string TEXT NOT NULL,
        matched_catalog_id TEXT NOT NULL,
        final_quoted_unit_price REAL NOT NULL,
        compliance_verified TEXT NOT NULL,
        quote_date TEXT NOT NULL,
        FOREIGN KEY(matched_catalog_id) REFERENCES product_catalog(catalog_id)
    )
    """)
    
    # Seed standard mock industrial vendor rows safely if empty
    cursor.execute("SELECT COUNT(*) FROM product_catalog")
    if cursor.fetchone()[0] == 0:
        # Core material definitions
        materials = [
            ("PART-SS304-4896", "Stainless Steel", "304", "Sheet", "48x96 in", "ASTM A240", "MTR_REQUIRED"),
            ("PART-CS40-2IN", "Carbon Steel", "Grade B", "Pipe", "2 in SCH 40", "ASTM A53", "DOMESTIC_ONLY")
        ]
        cursor.executemany("INSERT INTO product_catalog VALUES (?,?,?,?,?,?,?)", materials)
        
        # Multiple alternative vendor cost tiers (Availability Strategy)
        pricing = [
            ("PART-SS304-4896", "Alpha Metal Supply", 120.00, "sheet", 14),
            ("PART-SS304-4896", "Express Alloys (Local)", 145.00, "sheet", 2),
            ("PART-CS40-2IN", "Global Pipe Corp", 45.50, "length", 30),
            ("PART-CS40-2IN", "Mid Atlantic Iron", 52.00, "length", 5)
        ]
        cursor.executemany("INSERT INTO vendor_pricing (catalog_id, vendor_name, cost_per_unit, unit_of_measure, lead_time_days) VALUES (?,?,?,?,?)", pricing)
        
        # Historical record footprints
        history = [
            ("Q-99821", "Apex Engineering", "304 SS sheet 16ga 4x8", "PART-SS304-4896", 135.00, "TRUE", "2025-11-12"),
            ("Q-99410", "Apex Engineering", "Stainless 304, 0.060 in, 48 x 96", "PART-SS304-4896", 138.00, "TRUE", "2026-02-18")
        ]
        cursor.executemany("INSERT INTO historical_quotes VALUES (?,?,?,?,?,?,?)", history)
        
    conn.commit()
    conn.close()

# =====================================================================
# 3. KNOWLEDGE MATCHING VECTOR LAYER (ChromaDB Engine)
# =====================================================================
def sync_vector_stores():
    """Syncs relational database tracking entries into searchable vectors."""
    chroma_client = chromadb.PersistentClient(path=VECTOR_PATH)
    
    try:
        chroma_client.delete_collection("semantic_catalog")
        chroma_client.delete_collection("historical_rfq_strings")
    except Exception:
        pass
        
    catalog_coll = chroma_client.create_collection(name="semantic_catalog")
    history_coll = chroma_client.create_collection(name="historical_rfq_strings")
    
    # Read rows from SQLite database to build vector documents
    conn = sqlite3.connect(DB_PATH)
    
    # Populate Active Material Collection
    df_cat = pd.read_sql_query("SELECT * FROM product_catalog", conn)
    cat_ids, cat_docs, cat_meta = [], [], []
    for _, row in df_cat.iterrows():
        cat_ids.append(row['catalog_id'])
        cat_docs.append(f"Material: {row['material']} Grade: {row['grade']} Form: {row['form']} Dimensions: {row['dimensions']} Standard: {row['standard']}")
        cat_meta.append({"compliance": row['compliance_flags']})
    if cat_ids:
        catalog_coll.add(ids=cat_ids, documents=cat_docs, metadatas=cat_meta)
        
    # Populate Historical Context Collection
    df_hist = pd.read_sql_query("SELECT * FROM historical_quotes", conn)
    hist_ids, hist_docs, hist_meta = [], [], []
    for _, row in df_hist.iterrows():
        hist_ids.append(row['quote_id'])
        hist_docs.append(row['raw_buyer_string'])
        hist_meta.append({"customer": row['customer_name'], "matched_id": row['matched_catalog_id']})
    if hist_ids:
        history_coll.add(ids=hist_ids, documents=hist_docs, metadatas=hist_meta)
        
    conn.close()
    return catalog_coll, history_coll

# =====================================================================
# 4. CROSS-COLLECTION RETRIEVAL RESOLUTION (Hybrid RAG Router)
# =====================================================================
def resolve_quote_pricing(parsed_line: ParsedRFQLine, target_customer: str):
    """Executes a hybrid search to resolve the best catalog item and check target history."""
    chroma_client = chromadb.PersistentClient(path=VECTOR_PATH)
    catalog_coll = chroma_client.get_collection("semantic_catalog")
    history_coll = chroma_client.get_collection("historical_rfq_strings")
    
    # Create query string matching structural variables
    search_query = f"Material: {parsed_line.material} Grade: {parsed_line.grade} Dimensions: {parsed_line.dimensions}"
    
    # Query structural inventory database footprint
    cat_res = catalog_coll.query(query_texts=[search_query], n_results=1)
    if not cat_res['ids'] or not cat_res['ids'][0]:
        return {"status": "AMBIGUOUS", "message": "No closely matching items found inside catalog inventory."}
        
    matched_catalog_id = cat_res['ids'][0][0]
    
    # Query historical data spaces to check validation footprints
    hist_res = history_coll.query(query_texts=[parsed_line.raw_input], n_results=3)
    
    customer_validation = []
    if hist_res['ids'] and hist_res['ids'][0]:
        for i in range(len(hist_res['ids'][0])):
            meta = hist_res['metadatas'][0][i]
            if meta['customer'].lower() == target_customer.lower() and meta['matched_id'] == matched_catalog_id:
                customer_validation.append({
                    "past_quote_id": hist_res['ids'][0][i],
                    "matched_string": hist_res['documents'][0][i]
                })
                
    # Pull multi-vendor options from relational registry to construct comparison metrics
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT vendor_name, cost_per_unit, unit_of_measure, lead_time_days 
        FROM vendor_pricing WHERE catalog_id = ?
    """, (matched_catalog_id,))
    vendor_options = cursor.fetchall()
    conn.close()
    
    vendors = [
        {"vendor": v[0], "cost": v[1], "unit": v[2], "lead_time": v[3]}
        for v in vendor_options
    ]
    
    return {
        "status": "MATCHED",
        "resolved_catalog_id": matched_catalog_id,
        "vendor_pricing_tiers": vendors,
        "historical_customer_validation": customer_validation if customer_validation else "No identical past material combinations found for this client account."
    }

# =====================================================================
# PIPELINE EXECUTION ENTRYPOINT
# =====================================================================
if __name__ == "__main__":
    print("🚀 Initializing local storage registers...")
    init_storage_layers()
    sync_vector_stores()
    
    # Simulate an inbound messy line payload generated by your parser teammate
    simulated_incoming_payload = ParsedRFQLine(
        raw_input="Stainless 304, 0.060 in, 48 x 96",
        material="Stainless Steel",
        grade="304",
        form="Sheet",
        dimensions="48x96 in",
        quantity=15
    )
    
    print("\n🔍 Running Hybrid Material Verification Router...")
    resolution_metrics = resolve_quote_pricing(simulated_incoming_payload, target_customer="Apex Engineering")
    print(json.dumps(resolution_metrics, indent=4))


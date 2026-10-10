"""Initialize demo index once per process start, then serve one API worker."""
import os
from pathlib import Path
import uvicorn
from dotenv import load_dotenv
from backend.app.retrieval.embeddings import NicrronEmbeddings
from backend.app.retrieval.vector_search import RetrievalIndex, load_products
from chromadb.errors import NotFoundError

ROOT = Path(__file__).resolve().parents[1]


def initialize_index():
    load_dotenv(ROOT / '.env')
    catalog = load_products(ROOT / 'backend/data/fixtures/retrieval/supplier_catalog.json')
    index = RetrievalIndex(Path(os.getenv('CHROMA_PATH', str(ROOT / '.local/chroma'))), NicrronEmbeddings())
    try:
        collection = index.load_index()
    except NotFoundError:
        index.build_index(catalog.products, catalog.catalog_version)
        return
    if collection.metadata.get('catalog_version') != catalog.catalog_version or set(collection.get()['ids']) != {p.sku for p in catalog.products}:
        index.build_index(catalog.products, catalog.catalog_version)


if __name__ == '__main__':
    initialize_index()
    uvicorn.run('backend.app.main:app', host='0.0.0.0', port=int(os.getenv('PORT','8000')), workers=1)

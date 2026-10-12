"""Content-addressed, rebuildable Chroma index over a SQLite catalog snapshot."""
import hashlib
from pathlib import Path

import chromadb
from chromadb.errors import NotFoundError

from .models import Product


class IndexUnavailable(RuntimeError):
    pass


def product_text(p: Product):
    return '; '.join(str(v) for v in [p.material, p.grade, p.form, p.dimensions, p.standard, p.description] if v)


class RetrievalIndex:
    def __init__(self, path: Path, embedder):
        self.client = chromadb.PersistentClient(path=str(path))
        self.embedder = embedder

    def collection_name(self, version):
        suffix = hashlib.sha256(f'{self.embedder.model}:{version}'.encode()).hexdigest()[:32]
        return 'rfq-' + suffix

    def load_index(self, version):
        try:
            collection = self.client.get_collection(self.collection_name(version), embedding_function=None)
        except NotFoundError as exc:
            raise IndexUnavailable('Index missing or stale for the SQLite snapshot; run index') from exc
        metadata = collection.metadata or {}
        if metadata.get('embedding_model') != self.embedder.model or metadata.get('catalog_version') != version:
            raise IndexUnavailable('Index model/version mismatch; rebuild index')
        if metadata.get('state') != 'ready' or not metadata.get('embedding_dimensions'):
            raise IndexUnavailable('Index build incomplete; run index again')
        if (collection.configuration.get('hnsw') or {}).get('space') != 'cosine':
            raise IndexUnavailable('Index metric is not cosine')
        return collection

    def build_index(self, products: list[Product], version: str):
        if len({p.catalog_id for p in products}) != len(products):
            raise ValueError('Catalog IDs must be unique')
        if not products:
            return {'indexed_products': 0, 'catalog_version': version, 'status': 'empty_catalog'}
        try:
            existing = self.load_index(version)
            if existing.count() == len(products):
                return {'indexed_products': existing.count(), 'catalog_version': version, 'status': 'already_indexed'}
        except IndexUnavailable:
            pass
        metadata = {'embedding_model': self.embedder.model, 'catalog_version': version, 'state': 'building'}
        collection = self.client.get_or_create_collection(self.collection_name(version), embedding_function=None,
            metadata=metadata, configuration={'hnsw': {'space': 'cosine'}})
        if (collection.configuration.get('hnsw') or {}).get('space') != 'cosine':
            raise ValueError('Existing collection uses an incompatible metric; choose a new Chroma path')
        collection.modify(metadata=metadata)
        dimensions = None
        # Batch indexing; queries never rebuild. Partial builds remain unavailable.
        for offset in range(0, len(products), 64):
            batch = products[offset:offset+64]
            vectors = self.embedder.embed([product_text(p) for p in batch])
            if len(vectors) != len(batch) or not vectors or not vectors[0]:
                raise ValueError('Embedding batch size mismatch or empty vectors')
            current = len(vectors[0])
            if any(len(v) != current for v in vectors) or dimensions not in (None, current):
                raise ValueError('Embedding dimensions changed during indexing')
            dimensions = current
            collection.upsert(ids=[p.catalog_id for p in batch], embeddings=vectors,
                documents=[product_text(p) for p in batch],
                metadatas=[{'material': p.material or '', 'grade': p.grade or '', 'form': p.form or ''} for p in batch])
        stale = set(collection.get()['ids']) - {p.catalog_id for p in products}
        if stale:
            collection.delete(ids=sorted(stale))
        collection.modify(metadata={**metadata, 'state': 'ready', 'embedding_dimensions': dimensions})
        return {'indexed_products': collection.count(), 'catalog_version': version, 'status': 'indexed'}

    def search_semantic(self, text: str, version: str, top_k=20, material=None):
        collection = self.load_index(version)
        if not collection.count():
            return []
        vectors = self.embedder.embed([text])
        if len(vectors) != 1 or len(vectors[0]) != collection.metadata['embedding_dimensions']:
            raise ValueError('Query embedding dimensions differ from index')
        options = {'where': {'material': material}} if material else {}
        result = collection.query(query_embeddings=vectors, n_results=min(top_k, collection.count()),
                                  include=['distances'], **options)
        return list(zip(result['ids'][0], result['distances'][0]))

"""Persistent D2 retrieval starter. Chroma is a rebuildable index."""

from math import isclose
from pathlib import Path

import chromadb

from .models import ParsedRFQ, Product, SyntheticCatalog

COLLECTION = "rfqflow-synthetic-nicrron-v1"


def load_products(path: Path) -> SyntheticCatalog:
    """Temporary fixture adapter; D3 will provide records from SQLite instead."""
    return SyntheticCatalog.model_validate_json(path.read_text())


def product_text(product: Product) -> str:
    return (
        f"{product.material_family} grade {product.material_grade} {product.product_form}. "
        f"Thickness {product.thickness_in:g} inches. "
        f"Width {product.width_in:g} inches. Length {product.length_in:g} inches. "
        f"{product.description}"
    )


class RetrievalIndex:
    def __init__(self, path: Path, embedder):
        self.client = chromadb.PersistentClient(path=str(path))
        self.embedder = embedder

    def load_index(self):
        collection = self.client.get_collection(COLLECTION, embedding_function=None)
        self._check_collection(collection)
        if not collection.metadata.get("catalog_version") or not collection.metadata.get("embedding_dimensions"):
            raise ValueError("Index metadata is incomplete; seed the index before querying")
        return collection

    def _check_collection(self, collection):
        if (collection.metadata or {}).get("embedding_model") != self.embedder.model:
            raise ValueError("Embedding model differs from index; use a new --db directory and seed it")
        if (collection.configuration.get("hnsw") or {}).get("space") != "cosine":
            raise ValueError("Index does not use cosine distance; use a new --db directory and seed it")

    def build_index(self, products: list[Product], catalog_version: str):
        if not products or len({p.sku for p in products}) != len(products):
            raise ValueError("Index needs nonempty records with unique SKUs")
        texts = [product_text(p) for p in products]
        vectors = self.embedder.embed(texts)
        collection = self.client.get_or_create_collection(
            COLLECTION,
            embedding_function=None,
            metadata={"embedding_model": self.embedder.model, "catalog_version": catalog_version},
            configuration={"hnsw": {"space": "cosine"}},
        )
        self._check_collection(collection)
        dimensions = len(vectors[0])
        if collection.metadata.get("embedding_dimensions", dimensions) != dimensions:
            raise ValueError("Embedding dimensions changed; use a new --db directory and seed it")
        collection.upsert(
            ids=[p.sku for p in products], documents=texts, embeddings=vectors,
            metadatas=[p.model_dump() for p in products],
        )
        stale = set(collection.get()["ids"]) - {p.sku for p in products}
        if stale:
            collection.delete(ids=sorted(stale))
        collection.modify(metadata={**collection.metadata, "embedding_model": self.embedder.model,
                                    "embedding_dimensions": dimensions, "catalog_version": catalog_version})
        return collection.count()

    def retrieve_for_rfq(self, parsed_rfq: ParsedRFQ, top_k: int = 3) -> dict:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        collection = self.load_index()
        items = []
        for line in parsed_rfq.items:
            spec = line.specification
            filters = [{field: getattr(spec, field)} for field in
                       ("material_family", "material_grade", "product_form") if getattr(spec, field)]
            kwargs = {"where": {"$and": filters} if len(filters) > 1 else filters[0]} if filters else {}
            candidates = []
            if collection.count():
                query_vectors = self.embedder.embed([line.original_text])
                if len(query_vectors[0]) != collection.metadata["embedding_dimensions"]:
                    raise ValueError("Query embedding dimensions differ from the stored index")
                result = collection.query(
                    query_embeddings=query_vectors,
                    n_results=min(top_k, collection.count()), include=["metadatas", "distances"], **kwargs,
                )
                for metadata, distance in zip(result["metadatas"][0], result["distances"][0]):
                    conflicts = []
                    for name, requested in (("thickness", spec.thickness.normalized_inches),
                                            ("width", spec.width.value_in), ("length", spec.length.value_in)):
                        if requested is None:
                            conflicts.append(f"Requested {name} unresolved; equivalence not established")
                        # Numerical roundoff only, not a manufacturing tolerance.
                        elif not isclose(requested, metadata[f"{name}_in"], rel_tol=0, abs_tol=1e-9):
                            conflicts.append(f"{name} differs: requested {requested:g} in, catalog {metadata[f'{name}_in']:g} in")
                    candidates.append({**metadata, "distance": distance,
                                       "validation_status": "candidate_only", "potential_conflicts": conflicts})
            warnings = [*line.ambiguities, *[f"Missing field: {f}" for f in line.missing_fields],
                        "Demo catalog only; supplier suitability and compliance have not been verified",
                        "No historical quotes, supplier prices, benchmarks, or compliance evidence loaded"]
            if not candidates:
                warnings.append("No candidates found for the supplied material/grade/form")
            items.append({"line_id": line.line_id, "query_text": line.original_text,
                          "supplier_candidates": candidates, "historical_quotes": [], "supplier_prices": [],
                          "market_benchmarks": [], "compliance_evidence": [], "warnings": warnings})
        return {"rfq_id": parsed_rfq.rfq_id, "retrieval_method": "semantic_with_metadata_filters",
                "embedding_model": self.embedder.model, "catalog_version": collection.metadata["catalog_version"],
                "distance_metric": "cosine; lower is closer, not a compatibility probability", "items": items}

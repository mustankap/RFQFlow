"""Run from repository root: python -m backend.app.retrieval seed|query."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .embeddings import NicrronEmbeddings
from .models import ParsedRFQ
from .vector_search import RetrievalIndex, load_products

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "backend/data/fixtures/retrieval"


def main():
    parser = argparse.ArgumentParser(description="Synthetic RFQ demo with real Nicrron embeddings")
    parser.add_argument("command", choices=["seed", "query"])
    parser.add_argument("--db", type=Path, default=ROOT / ".local/chroma")
    parser.add_argument("--catalog", type=Path, default=FIXTURES / "supplier_catalog.json")
    parser.add_argument("--rfq", type=Path, default=FIXTURES / "parsed_rfq_ideal.json")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    try:
        index = RetrievalIndex(args.db, NicrronEmbeddings())
        if args.command == "seed":
            catalog = load_products(args.catalog)
            print(json.dumps({"indexed_products": index.build_index(catalog.products, catalog.catalog_version),
                              "database": str(args.db), "embedding_model": index.embedder.model}))
        else:
            rfq = ParsedRFQ.model_validate_json(args.rfq.read_text())
            print(json.dumps(index.retrieve_for_rfq(rfq), indent=2))
    except Exception as exc:
        # CLI failure stays nonzero; do not return fabricated successful evidence.
        parser.exit(1, f"Retrieval failed: {exc}\n")


if __name__ == "__main__":
    main()

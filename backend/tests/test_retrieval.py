import subprocess
import sys
from pathlib import Path

import httpx
import chromadb
import pytest
from pydantic import ValidationError

from backend.app.retrieval.embeddings import NicrronEmbeddings
from backend.app.retrieval.models import ParsedRFQ, SyntheticCatalog
from backend.app.retrieval.vector_search import COLLECTION, RetrievalIndex, load_products

FIXTURES = Path(__file__).parents[1] / "data/fixtures/retrieval"


class TestEmbeddings:
    """Test double only: exercises storage/filtering, not semantic quality."""
    __test__ = False
    model = "test-only-constant-vectors"

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def catalog():
    return load_products(FIXTURES / "supplier_catalog.json")


@pytest.fixture
def rfq():
    return ParsedRFQ.model_validate_json((FIXTURES / "parsed_rfq_ideal.json").read_text())


@pytest.fixture
def index(tmp_path, catalog):
    result = RetrievalIndex(tmp_path / "chroma", TestEmbeddings())
    result.build_index(catalog.products, catalog.catalog_version)
    return result


def test_filtering_sources_and_dimension_conflicts(index, rfq):
    result = index.retrieve_for_rfq(rfq)
    assert [i["line_id"] for i in result["items"]] == [i.line_id for i in rfq.items]
    first = result["items"][0]["supplier_candidates"]
    assert {p["sku"] for p in first} == {"DEMO-SS304-060", "DEMO-SS304-120"}
    assert all(p["source_id"] and p["is_synthetic"] and p["validation_status"] == "candidate_only" for p in first)
    thicker = next(p for p in first if p["sku"] == "DEMO-SS304-120")
    assert any("thickness differs" in warning for warning in thicker["potential_conflicts"])
    assert result["items"][0]["supplier_prices"] == []


def test_unknown_product_and_ambiguous_dimensions(index, rfq):
    rfq.items[0].specification.material_grade = "UNKNOWN"
    rfq.items[1].specification.width.value_in = None
    rfq.items[1].specification.width.unit_status = "ambiguous"
    result = index.retrieve_for_rfq(rfq)
    assert result["items"][0]["supplier_candidates"] == []
    assert any("No candidates" in w for w in result["items"][0]["warnings"])
    assert any("width unresolved" in w for w in result["items"][1]["supplier_candidates"][0]["potential_conflicts"])


def test_reseed_removes_stale_products_and_is_idempotent(index, catalog):
    assert index.build_index(catalog.products, catalog.catalog_version) == 6
    assert index.build_index(catalog.products[:1], "smaller-fixture") == 1
    assert index.load_index().metadata["catalog_version"] == "smaller-fixture"


def test_persistence_in_separate_process(index, tmp_path):
    code = "import chromadb,sys; c=chromadb.PersistentClient(path=sys.argv[1]); print(c.get_collection(sys.argv[2],embedding_function=None).count())"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "chroma"), COLLECTION],
                            check=True, text=True, capture_output=True)
    assert result.stdout.strip() == "6"


def test_model_mismatch_is_rejected(index):
    index.embedder.model = "different-model"
    with pytest.raises(ValueError, match="Embedding model differs"):
        index.load_index()


def test_wrong_distance_metric_rejected(tmp_path):
    chromadb.PersistentClient(path=str(tmp_path)).create_collection(
        COLLECTION, embedding_function=None,
        metadata={"embedding_model": TestEmbeddings.model},
        configuration={"hnsw": {"space": "l2"}},
    )
    with pytest.raises(ValueError, match="cosine"):
        RetrievalIndex(tmp_path, TestEmbeddings()).load_index()


def test_changed_query_dimensions_rejected(index, rfq):
    index.embedder.embed = lambda texts: [[1.0, 0.0] for _ in texts]
    with pytest.raises(ValueError, match="Query embedding dimensions"):
        index.retrieve_for_rfq(rfq)


def test_numerical_roundoff_is_not_a_dimension_conflict(index, rfq):
    rfq.items[0].specification.thickness.normalized_inches = .06000000000000001
    candidate = next(c for c in index.retrieve_for_rfq(rfq)["items"][0]["supplier_candidates"]
                     if c["sku"] == "DEMO-SS304-060")
    assert candidate["potential_conflicts"] == []


def test_bad_fixtures_rejected(catalog, rfq):
    data = catalog.model_dump()
    data["products"].append(data["products"][0])
    with pytest.raises(ValidationError, match="unique"):
        SyntheticCatalog.model_validate(data)
    data = rfq.model_dump()
    data["items"].append(data["items"][0])
    with pytest.raises(ValidationError, match="unique"):
        ParsedRFQ.model_validate(data)


def test_nonfinite_dimensions_rejected(catalog):
    data = catalog.model_dump()
    data["products"][0]["width_in"] = float("inf")
    with pytest.raises(ValidationError):
        SyntheticCatalog.model_validate(data)


def test_nicrron_requires_key(monkeypatch):
    monkeypatch.delenv("NICRRON_API_KEY", raising=False)
    with pytest.raises(ValueError, match="NICRRON_API_KEY"):
        NicrronEmbeddings()


def test_nicrron_endpoint_model_and_response_order(monkeypatch):
    monkeypatch.setenv("NICRRON_API_KEY", "test-key-not-real")
    monkeypatch.setenv("NICRRON_EMBEDDING_MODEL", "openai/text-embedding-3-small")

    def post(url, **kwargs):
        assert url == "https://api.nicrron.ai/v1/embeddings"
        assert kwargs["json"] == {"model": "openai/text-embedding-3-small", "input": ["one", "two"]}
        assert kwargs["headers"]["Authorization"] == "Bearer test-key-not-real"
        return httpx.Response(200, json={"model": "openai/text-embedding-3-small", "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})

    monkeypatch.setattr(httpx, "post", post)
    assert NicrronEmbeddings().embed(["one", "two"]) == [[1, 0], [0, 1]]


def test_provider_model_substitution_rejected(monkeypatch):
    monkeypatch.setenv("NICRRON_API_KEY", "test-key-not-real")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(
        200, json={"model": "different-model", "data": [{"index": 0, "embedding": [1, 0]}]}))
    with pytest.raises(ValueError, match="model identity"):
        NicrronEmbeddings().embed(["one"])


def test_nicrron_retries_are_bounded(monkeypatch):
    monkeypatch.setenv("NICRRON_API_KEY", "test-key-not-real")
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(503)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("backend.app.retrieval.embeddings.time.sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="three attempts"):
        NicrronEmbeddings().embed(["one"])
    assert len(calls) == 3


@pytest.mark.parametrize("rows", [[], [{"index": 0, "embedding": []}], [{"index": 0, "embedding": [float('nan')]}]])
def test_malformed_embeddings_rejected(rows):
    with pytest.raises(ValueError):
        NicrronEmbeddings._vectors({"data": rows}, 1)

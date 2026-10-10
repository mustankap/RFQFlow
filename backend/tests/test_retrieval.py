import httpx
import pytest
from backend.app.retrieval.embeddings import NicrronEmbeddings


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


def test_malformed_provider_response_becomes_validation_error(monkeypatch):
    monkeypatch.setenv('NICRRON_API_KEY','test-only-key')
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(200,json={'model':'openai/text-embedding-3-small'}))
    with pytest.raises(ValueError,match='Malformed'):
        NicrronEmbeddings().embed(['one'])

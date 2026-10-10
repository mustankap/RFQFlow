"""Nicrron embeddings only. No local-model or cross-model fallback."""

import math
import os
import time
from uuid import uuid4

from .observability import embedding_event

import httpx


class NicrronEmbeddings:
    def __init__(self):
        self.model = os.getenv("NICRRON_EMBEDDING_MODEL", "openai/text-embedding-3-small")
        self.api_key = os.getenv("NICRRON_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("Set NICRRON_API_KEY in the gitignored .env before indexing or querying")
        if not self.model or self.model.startswith("nicrron/"):
            raise ValueError("Choose a fixed embedding model, not an automatic routing mode")

    def embed(self, texts: list[str]) -> list[list[float]]:
        started = time.monotonic()
        try:
            return self._embed(texts)
        except (RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
            embedding_event(model=self.model, texts=texts, status='error', error_type=type(exc).__name__,
                            latency_ms=int((time.monotonic()-started)*1000))
            if isinstance(exc, (KeyError, TypeError)):
                raise ValueError('Malformed Nicrron embedding response') from exc
            raise

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started = time.monotonic()
        request_id = str(uuid4())
        for attempt in range(3):
            try:
                response = httpx.post(
                    "https://api.nicrron.ai/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}", "X-Request-ID": request_id},
                    json={"model": self.model, "input": texts},
                    timeout=30,
                )
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise RuntimeError("Nicrron embedding request failed after three attempts") from exc
            else:
                if response.is_success:
                    payload = response.json()
                    if payload.get("model") not in {self.model, self.model.split("/")[-1]}:
                        raise ValueError("Nicrron returned a different or missing embedding model identity")
                    vectors = self._vectors(payload, len(texts))
                    embedding_event(model=self.model, texts=texts, status='success', dimensions=len(vectors[0]),
                                    input_count=len(texts), latency_ms=int((time.monotonic()-started)*1000),
                                    tokens=(payload.get('usage') or {}).get('prompt_tokens', 0),
                                    request_id=response.headers.get('x-request-id', request_id))
                    return vectors
                if response.status_code != 429 and response.status_code < 500:
                    raise RuntimeError(f"Nicrron embeddings returned HTTP {response.status_code}; check key/model access")
                if attempt == 2:
                    raise RuntimeError(f"Nicrron embeddings returned HTTP {response.status_code} after three attempts")
            time.sleep(attempt + 1)
        raise RuntimeError("Nicrron embedding request failed")

    @staticmethod
    def _vectors(payload: dict, count: int) -> list[list[float]]:
        rows = sorted(payload["data"], key=lambda row: row["index"])
        if [row["index"] for row in rows] != list(range(count)):
            raise ValueError("Nicrron returned missing or duplicate embedding indices")
        vectors = [row["embedding"] for row in rows]
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1 or 0 in dimensions:
            raise ValueError("Nicrron returned inconsistent or empty embeddings")
        if not all(type(x) in (int, float) and math.isfinite(x) for v in vectors for x in v):
            raise ValueError("Nicrron returned non-finite or non-numeric embeddings")
        return vectors

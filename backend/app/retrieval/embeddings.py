"""Nicrron embeddings only. No local-model or cross-model fallback."""

from backend.app.deployment import reserve_model_call

import math
import os
import time

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
        if not texts:
            return []
        for attempt in range(3):
            try:
                reserve_model_call()
                response = httpx.post(
                    "https://api.nicrron.ai/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
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
                    return self._vectors(payload, len(texts))
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
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for v in vectors for x in v):
            raise ValueError("Nicrron returned non-finite or non-numeric embeddings")
        return vectors

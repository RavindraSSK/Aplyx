"""Embedding providers behind one interface.

Selection (EMBEDDING_PROVIDER=auto):
  1. voyage      - Voyage AI API (VOYAGE_API_KEY set). Recommended for Vercel.
  2. local       - sentence-transformers, if installed (`pip install -e .[ml]`).
  3. hashing     - dependency-free feature-hashing bag of words. Always works,
                   low quality; the stored `embedding_model` records which one
                   produced a vector so mismatches are detectable, never silent.
"""
import hashlib
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
_WORD_RE = re.compile(r"[a-z0-9+#.]{2,}")


@dataclass
class Embedding:
    vector: list[float]
    model: str

    @property
    def dim(self) -> int:
        return len(self.vector)


class EmbeddingProvider:
    name: str
    model: str

    def embed(self, text: str) -> Embedding:  # pragma: no cover - interface
        raise NotImplementedError


class HashingProvider(EmbeddingProvider):
    """Deterministic 512-dim feature hashing, L2-normalized. No network, no deps."""
    name = "hashing"
    model = "hashing-bow-512"
    dim = 512

    def embed(self, text: str) -> Embedding:
        vec = [0.0] * self.dim
        for tok in _WORD_RE.findall(text.lower()):
            h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return Embedding([v / norm for v in vec], self.model)


class VoyageProvider(EmbeddingProvider):
    name = "voyage"
    API_URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def embed(self, text: str) -> Embedding:
        resp = httpx.post(
            self.API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"input": [text], "model": self.model, "input_type": "document"},
            timeout=get_settings().http_timeout_seconds,
        )
        resp.raise_for_status()
        return Embedding(resp.json()["data"][0]["embedding"], self.model)


class LocalProvider(EmbeddingProvider):
    name = "local"

    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer  # optional dep

        self.model = model
        self._st = SentenceTransformer(model)

    def embed(self, text: str) -> Embedding:
        return Embedding([float(x) for x in self._st.encode(text)], self.model)


@lru_cache
def get_provider() -> EmbeddingProvider:
    s = get_settings()
    choice = s.embedding_provider
    if choice in ("auto", "voyage") and s.voyage_api_key:
        return VoyageProvider(s.voyage_api_key, s.voyage_model)
    if choice in ("auto", "local"):
        try:
            return LocalProvider(s.embedding_model)
        except ImportError:
            if choice == "local":
                raise
    if choice == "voyage":
        raise RuntimeError("EMBEDDING_PROVIDER=voyage but VOYAGE_API_KEY is not set")
    logger.warning("Using hashing embedding fallback - set VOYAGE_API_KEY for real embeddings")
    return HashingProvider()


def embed_text(text: str) -> Embedding:
    return get_provider().embed(text)

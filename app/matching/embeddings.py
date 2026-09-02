"""Text similarity for resume <-> job description.

Uses sentence-transformers when installed (`pip install -e .[ml]`); otherwise
falls back to a dependency-free TF-IDF cosine so matching still works.
"""
import math
import re
from collections import Counter
from functools import lru_cache

from app.config import get_settings

_WORD_RE = re.compile(r"[a-z0-9+#.]{2,}")

_STOPWORDS = frozenset(
    "the a an and or of to in for with on at by from as is are was were be been "
    "this that these those it its we you your our their they he she will would "
    "can could should may might must have has had do does did not no but if than "
    "then so such about into over under more most other some any all each".split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


def _tfidf_cosine(a: str, b: str) -> float:
    """Cosine similarity over term frequencies (idf omitted for a 2-doc corpus)."""
    ta, tb = Counter(_tokenize(a)), Counter(_tokenize(b))
    if not ta or not tb:
        return 0.0
    common = set(ta) & set(tb)
    dot = sum(ta[t] * tb[t] for t in common)
    norm = math.sqrt(sum(v * v for v in ta.values())) * math.sqrt(
        sum(v * v for v in tb.values())
    )
    return dot / norm if norm else 0.0


@lru_cache
def _load_st_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    return SentenceTransformer(get_settings().embedding_model)


def similarity(a: str, b: str) -> float:
    """Return similarity in [0, 1] between two texts."""
    model = _load_st_model()
    if model is not None:
        from sentence_transformers.util import cos_sim

        emb = model.encode([a, b])
        return max(0.0, min(1.0, float(cos_sim(emb[0], emb[1]))))
    return _tfidf_cosine(a, b)


def backend_name() -> str:
    return "sentence-transformers" if _load_st_model() is not None else "tfidf-fallback"

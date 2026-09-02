import math

from app.embeddings.provider import HashingProvider, get_provider


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_hashing_provider_is_deterministic_and_normalized():
    p = HashingProvider()
    e1 = p.embed("python machine learning pytorch")
    e2 = p.embed("python machine learning pytorch")
    assert e1.vector == e2.vector
    assert e1.dim == 512 and e1.model == "hashing-bow-512"
    assert abs(math.sqrt(sum(v * v for v in e1.vector)) - 1.0) < 1e-9


def test_hashing_provider_has_signal():
    p = HashingProvider()
    resume = p.embed("python pytorch machine learning transformers nlp").vector
    near = p.embed("machine learning engineer pytorch nlp transformers").vector
    far = p.embed("registered nurse hospital patient care shifts").vector
    assert _cos(resume, near) > _cos(resume, far)


def test_auto_provider_without_keys_falls_back_to_hashing(monkeypatch):
    get_provider.cache_clear()
    monkeypatch.setenv("VOYAGE_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    from app.config import get_settings

    get_settings.cache_clear()
    assert get_provider().name == "hashing"
    get_settings.cache_clear()
    get_provider.cache_clear()

"""Dialect-aware column types."""
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator


class EmbeddingVector(TypeDecorator):
    """pgvector `vector` on PostgreSQL (when the extension exists), JSON elsewhere.

    Stored as a plain list[float] either way. Similarity search is only
    available on PostgreSQL + pgvector; SQLite is for local dev/tests.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector())
            except ImportError:  # pragma: no cover
                pass
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]

"""Vercel serverless entrypoint — exposes the FastAPI app as ASGI."""
from app.main import app  # noqa: F401

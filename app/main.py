"""FastAPI application entrypoint."""
import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from app.api.routes import router
from app.config import get_settings
from app.db.session import init_db

DASHBOARD = Path(__file__).parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="jobagent", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def basic_auth_guard(request: Request, call_next):
    """If DASHBOARD_PASSWORD is set, require HTTP Basic auth on every route."""
    password = get_settings().dashboard_password
    if password:
        header = request.headers.get("authorization", "")
        supplied = ""
        if header.startswith("Basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode().partition(":")[2]
            except Exception:
                supplied = ""
        if not secrets.compare_digest(supplied, password):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="jobagent"'},
            )
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD, media_type="text/html")

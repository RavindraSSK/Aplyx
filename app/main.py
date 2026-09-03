"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.profile_routes import router as profile_router
from app.api.routes import router
from app.auth import ensure_owner, get_auth_provider
from app.config import get_settings
from app.db.session import get_session_factory, init_db
from app.db.tenancy import current_user_id

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = get_session_factory()()
    try:
        ensure_owner(db)
    finally:
        db.close()
    yield


class RestoreOriginalPath:
    """Vercel rewrites every request to /api/index?__path=<original>. If the
    function receives the rewritten path, put the original one back so
    FastAPI routing works. Harmless when the path was preserved."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and b"__path=" in scope.get("query_string", b""):
            params = parse_qsl(scope["query_string"].decode(), keep_blank_values=True)
            forced = next((v for k, v in params if k == "__path"), None)
            rest = [(k, v) for k, v in params if k != "__path"]
            scope = dict(scope)
            if forced is not None:
                scope["path"] = "/" + forced.lstrip("/")
                scope["raw_path"] = scope["path"].encode()
            scope["query_string"] = urlencode(rest).encode()
        await self.app(scope, receive, send)


app = FastAPI(title="jobagent", version="0.2.0", lifespan=lifespan)
app.add_middleware(RestoreOriginalPath)
app.include_router(router)
app.include_router(profile_router)
# check_dir=False: never crash the whole app if the bundle lacks the folder;
# /health reports it instead.
app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """Authenticate via the configured AuthProvider and scope the request to
    that user (tenancy contextvar -> Postgres RLS)."""
    provider = get_auth_provider()
    uid = provider.authenticate(request)
    if uid is None:
        return Response(status_code=401, headers=provider.challenge_headers())
    token = current_user_id.set(uid)
    try:
        return await call_next(request)
    finally:
        current_user_id.reset(token)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "static_present": (STATIC / "index.html").exists() and (STATIC / "app.css").exists(),
        "vertical_present": Path(get_settings().vertical_config_dir).joinpath(get_settings().vertical).exists(),
        "db": get_settings().database_url.split("://", 1)[0],
    }


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/profile", include_in_schema=False)
def profile_page():
    return FileResponse(STATIC / "profile.html", media_type="text/html")

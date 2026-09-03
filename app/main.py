"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
from pathlib import Path

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


app = FastAPI(title="jobagent", version="0.2.0", lifespan=lifespan)
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

import os
from contextlib import asynccontextmanager
from app.core.database import SessionLocal, engine
from app.services.git_coach_jobs import CoachWorkerLoop, worker_enabled, schema_ready

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.api import api_router
from app.core.config import parse_cors_origins, settings
from app.core.init_db import init_db

init_db()

@asynccontextmanager
async def lifespan(app):
    worker = CoachWorkerLoop(SessionLocal) if worker_enabled() and schema_ready(engine) else None
    app.state.git_coach_worker = worker
    if worker:
        worker.start()
    try:
        yield
    finally:
        if worker:
            worker.stop()


app = FastAPI(title="AI Private Tutor Backend", version="3.0", lifespan=lifespan)

from app.services.byok.http_boundary import install_byok_http_boundary
from app.services.byok.observability import install_byok_privacy_filters
install_byok_http_boundary(app)
install_byok_privacy_filters()

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

cors_origins = parse_cors_origins(settings.BACKEND_CORS_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
def read_root():
    return {
        "status": "running",
        "message": "AI Private Tutor backend service is running.",
        "version": "3.0",
    }

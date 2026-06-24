import os
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.routers import health
from app.slack import bolt_app as slack_bolt

settings = get_settings()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=False,
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("product_copilot_started", env=settings.environment)
    yield
    # Close pools on shutdown
    from app.db.feature_request_repo import close_pool
    await close_pool()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)

from app.routers import adk  # noqa:E402,F401
app.include_router(adk.router)

app.include_router(slack_bolt.router)

from app.routers import feature_requests  # noqa: E402,F401
app.include_router(feature_requests.router)

from app.routers import docs, pdf, plan_agent  # noqa: E402,F401
app.include_router(docs.router)
app.include_router(pdf.router)
app.include_router(plan_agent.router)
app.include_router(plan_agent._impl_router)
app.include_router(plan_agent._phases_router)

# Serve frontend static files
_frontend_static = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
if os.path.isdir(_frontend_static):
    app.mount("/static", StaticFiles(directory=_frontend_static), name="static")


@app.get("/")
async def root():
    return RedirectResponse(url="/index.html")


@app.get("/index.html")
async def index():
    from fastapi.responses import FileResponse
    _path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(_path):
        return FileResponse(_path, media_type="text/html")
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


@app.get("/{page}")
async def serve_page(page: str):
    """Serve frontend HTML pages (feature-requests.html, ingest.html, etc.)."""
    from fastapi.responses import FileResponse
    # Strip .html suffix so /index.html serves frontend/index.html
    _name = page.removesuffix(".html")
    _path = os.path.join(os.path.dirname(__file__), "..", "frontend", _name + ".html")
    if os.path.exists(_path):
        return FileResponse(_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")

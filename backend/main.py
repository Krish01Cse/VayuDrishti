# -*- coding: utf-8 -*-
"""
main.py — VayuDrishti FastAPI application entry point.

Wires together:
  - FastAPI app with CORS middleware
  - /api/v1/reports router (submit, fetch, list, nearby)
  - /health liveness probe
  - / root redirect → /docs
  - Global exception handler for unhandled errors
  - Startup / shutdown logging via lifespan context manager

Run locally:
    cd backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from config import get_settings
from routers import reports as reports_router

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(level: str) -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


settings = get_settings()
_configure_logging(settings.LOG_LEVEL)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan context manager (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup tasks, yield to serve requests, then run shutdown tasks."""
    # ---- Startup ----
    logger.info(
        "VayuDrishti %s starting up | vision=%s | localstack=%s",
        settings.APP_VERSION,
        settings.VISION_PROVIDER,
        settings.USE_LOCALSTACK,
    )
    logger.info(
        "S3 bucket: %s | DynamoDB table: %s",
        settings.S3_BUCKET_NAME,
        settings.DYNAMODB_TABLE_DUST_REPORTS,
    )
    if settings.USE_LOCALSTACK:
        logger.info("LocalStack endpoint: %s", settings.LOCALSTACK_ENDPOINT)
    logger.info("API docs available at http://127.0.0.1:8000/docs")

    yield  # Application runs here

    # ---- Shutdown ----
    logger.info("VayuDrishti %s shutting down.", settings.APP_VERSION)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "VayuDrishti — Urban dust-pollution reporting API. "
        "Residents submit photo reports; AI analyses images and builds investigation dossiers."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS middleware  (allows the Vite / React dev server to reach the API)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler so unhandled errors return structured JSON instead of a 500 traceback."""
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal error occurred. Please try again later."},
    )

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(reports_router.router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Root redirect  (/ → /docs for easy browser access)
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    """Redirect root to interactive API docs."""
    return RedirectResponse(url="/docs")

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"], summary="Liveness probe")
def health_check() -> dict:
    """Simple liveness probe — returns app name, version, and active config."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "vision_provider": settings.VISION_PROVIDER,
        "storage_provider": settings.STORAGE_PROVIDER,
        "use_localstack": settings.USE_LOCALSTACK,
        "s3_bucket": settings.S3_BUCKET_NAME,
        "dynamodb_table": settings.DYNAMODB_TABLE_DUST_REPORTS,
    }

# ---------------------------------------------------------------------------
# AWS Lambda entry point (for AWS Console Lambda / SAM deployments)
# ---------------------------------------------------------------------------
try:
    from mangum import Mangum

    # lifespan="off" is recommended for AWS Lambda serverless execution
    handler = Mangum(app, lifespan="off")
except ImportError:
    handler = None  # Non-lambda environments do not require mangum

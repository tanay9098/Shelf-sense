"""ShelfSense FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import error, router
from app.config import get_settings
from app.db.connection import DatabaseUnavailable, QueryFailed, get_client
from app.db.seed import ensure_seeded
from app.services.investigation_service import InvestigationError
from app.services.mutation_service import MutationError
from app.tools.investigation_tools import InvalidIdentifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("shelfsense")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = get_client()
    if not client.ping():
        log.error("FalkorDB is NOT reachable at %s:%s. The API will return 503 until it is started "
                  "(docker compose up -d falkordb).", settings.falkordb_host, settings.falkordb_port)
    elif settings.seed_on_startup:
        try:
            if ensure_seeded(client):
                log.info("Seeded demo graph '%s'.", client.graph_name)
        except (DatabaseUnavailable, QueryFailed) as exc:
            log.error("Seeding failed: %s", exc)
    yield


app = FastAPI(title="ShelfSense", version="0.1.0", lifespan=lifespan,
              description="Graph-powered retail availability investigations on FalkorDB (simulated demo data).")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.exception_handler(DatabaseUnavailable)
async def _db_down(_: Request, exc: DatabaseUnavailable):
    return error("DATABASE_UNAVAILABLE", str(exc), 503)


@app.exception_handler(QueryFailed)
async def _query_failed(_: Request, exc: QueryFailed):
    return error("QUERY_FAILED", str(exc), 502)


@app.exception_handler(InvestigationError)
async def _inv_error(_: Request, exc: InvestigationError):
    return error(exc.code, exc.message, exc.status, exc.details)


@app.exception_handler(MutationError)
async def _mut_error(_: Request, exc: MutationError):
    return error(exc.code, exc.message, exc.status)


@app.exception_handler(InvalidIdentifier)
async def _bad_id(_: Request, exc: InvalidIdentifier):
    return error("INVALID_ID", str(exc), 422)


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    issues = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg")}
              for e in exc.errors()]
    return error("VALIDATION_ERROR", "The request is invalid.", 422, {"issues": issues})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return error("INTERNAL_ERROR", "Something went wrong while processing the request.", 500)


app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")

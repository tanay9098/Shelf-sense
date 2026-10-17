"""HTTP API. All errors are returned as {"error": {code, message, details}}."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import seed
from app.db.connection import get_client
from app.models.investigation import InvestigateRequest, InvestigationResponse, MutationRequest
from app.services.investigation_service import InvestigationService, list_products, list_retailers
from app.services.mutation_service import MutationService, describe_allowlist
from app.tools.investigation_tools import TOOL_CATALOGUE

router = APIRouter(prefix="/api")


def error(code: str, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


@router.get("/health")
def health():
    s = get_settings()
    client = get_client()
    connected = client.ping()
    body = {
        "status": "ok" if connected else "degraded",
        "app": "ShelfSense",
        "data_mode": "simulated",
        "database": {"engine": "FalkorDB", "connected": connected, "graph": client.graph_name},
        "llm": {"provider": s.llm_provider, "enabled": s.llm_enabled},
        "demo_clock": s.demo_now,
    }
    if connected:
        try:
            body["database"]["counts"] = seed.graph_counts(client)
        except Exception:
            body["database"]["counts"] = None
    else:
        body["database"]["message"] = "FalkorDB is not reachable. Start it with `docker compose up -d falkordb`."
    return JSONResponse(status_code=200 if connected else 503, content=body)


@router.get("/demo/scenarios")
def scenarios():
    return {"scenarios": seed.SCENARIOS, "tools": TOOL_CATALOGUE}


@router.get("/retailers")
def retailers():
    return {"retailers": list_retailers(get_client())}


@router.get("/products")
def products():
    return {"products": list_products(get_client())}


@router.post("/investigate", response_model=InvestigationResponse)
def investigate(req: InvestigateRequest):
    svc = InvestigationService(get_client())
    return svc.investigate(question=req.question, retailer_id=req.retailer_id,
                           product_id=req.product_id, scenario_id=req.scenario_id)


@router.get("/demo/mutations")
def mutation_allowlist():
    return describe_allowlist()


@router.post("/demo/mutate")
def mutate(req: MutationRequest):
    return MutationService(get_client()).apply(req.entity_type, req.record_id, req.field, req.value, req.confirm)


@router.post("/demo/reset")
def reset():
    counts = seed.reset_graph(get_client())
    return {"status": "reset", "counts": counts}


@router.get("/graph")
def graph(retailer_id: str = Query(pattern=r"^R-\d{3}$"), product_id: str = Query(pattern=r"^P-\d{2}$")):
    """The limited investigation subgraph only (same queries as /investigate)."""
    result = InvestigationService(get_client()).investigate(retailer_id=retailer_id, product_id=product_id)
    return {"retailer_id": retailer_id, "product_id": product_id, "graph": result["graph"]}

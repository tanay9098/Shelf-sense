"""API tests. Integration tests use a real FalkorDB; the DB-down test points at a closed port."""
from __future__ import annotations

import pytest


def test_health_reports_db_unavailable(api_db_down):
    r = api_db_down.get("/api/health")
    assert r.status_code == 503
    body = r.json()
    assert body["database"]["connected"] is False
    assert "docker compose" in body["database"]["message"]
    assert "password" not in r.text.lower()


def test_investigate_returns_structured_503_when_db_down(api_db_down):
    r = api_db_down.post("/api/investigate", json={"scenario_id": "A"})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "DATABASE_UNAVAILABLE"
    assert "Traceback" not in r.text


def test_validation_errors_do_not_need_db(api_db_down):
    r = api_db_down.post("/api/investigate", json={"retailer_id": "R-104'; DROP", "product_id": "P-01"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = api_db_down.post("/api/investigate", json={})
    assert r.status_code == 422
    r = api_db_down.post("/api/investigate", json={"question": "x" * 501})
    assert r.status_code == 422


@pytest.mark.integration
def test_health_ok(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"]["connected"] is True
    assert body["database"]["counts"]["nodes"]["Retailer"] == 20
    assert body["data_mode"] == "simulated"


@pytest.mark.integration
def test_reference_endpoints(api):
    assert len(api.get("/api/retailers").json()["retailers"]) == 20
    assert 10 <= len(api.get("/api/products").json()["products"]) <= 15
    sc = api.get("/api/demo/scenarios").json()["scenarios"]
    assert len(sc) >= 4


@pytest.mark.integration
def test_investigate_scenario_shape(api):
    r = api.post("/api/investigate", json={"scenario_id": "A"})
    assert r.status_code == 200
    body = r.json()
    for key in ("investigation_id", "summary", "probable_cause", "observed_facts", "inferences",
                "missing_information", "evidence", "graph_path", "recommended_actions", "query_trace"):
        assert key in body
    assert body["probable_cause"]["code"] == "DELAYED_DELIVERY"


@pytest.mark.integration
def test_unknown_retailer_and_product(api):
    r = api.post("/api/investigate", json={"retailer_id": "R-999", "product_id": "P-01"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "RETAILER_NOT_FOUND"
    r = api.post("/api/investigate", json={"retailer_id": "R-104", "product_id": "P-99"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    r = api.post("/api/investigate", json={"question": "hello there"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ENTITY_NOT_IDENTIFIED"


@pytest.mark.integration
@pytest.mark.parametrize("payload,status,code", [
    ({"entity_type": "Order", "record_id": "O-1012", "field": "status", "value": "delivered", "confirm": True}, 422, "VALIDATION_ERROR"),
    ({"entity_type": "Delivery", "record_id": "DEL-1012", "field": "quantity", "value": 5, "confirm": True}, 422, "FIELD_NOT_ALLOWED"),
    ({"entity_type": "Delivery", "record_id": "DEL-1012", "field": "status", "value": "lost", "confirm": True}, 422, "INVALID_VALUE"),
    ({"entity_type": "Delivery", "record_id": "DEL-1012", "field": "status", "value": "delivered", "confirm": False}, 400, "CONFIRMATION_REQUIRED"),
    ({"entity_type": "Delivery", "record_id": "DEL-0000", "field": "status", "value": "delivered", "confirm": True}, 404, "RECORD_NOT_FOUND"),
    ({"entity_type": "Inventory", "record_id": "INV-W-01-P-01", "field": "quantity", "value": -4, "confirm": True}, 422, "INVALID_VALUE"),
    ({"entity_type": "Inventory", "record_id": "MATCH (n) DELETE n", "field": "quantity", "value": 1, "confirm": True}, 422, "VALIDATION_ERROR"),
])
def test_invalid_mutations(api, payload, status, code):
    r = api.post("/api/demo/mutate", json=payload)
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    # nothing changed
    assert api.post("/api/investigate", json={"scenario_id": "A"}).json()["probable_cause"]["code"] == "DELAYED_DELIVERY"


@pytest.mark.integration
def test_mutation_then_reset_restores_original_state(api):
    original = api.post("/api/investigate", json={"scenario_id": "A"}).json()
    m = api.post("/api/demo/mutate", json={"entity_type": "Delivery", "record_id": "DEL-1012", "field": "status",
                                          "value": "delivered", "confirm": True})
    assert m.status_code == 200 and m.json()["before"]["delivery"]["status"] == "delayed"
    changed = api.post("/api/investigate", json={"scenario_id": "A"}).json()
    assert changed["probable_cause"]["code"] != original["probable_cause"]["code"]

    reset = api.post("/api/demo/reset")
    assert reset.status_code == 200
    restored = api.post("/api/investigate", json={"scenario_id": "A"}).json()
    assert restored["probable_cause"] == original["probable_cause"]
    assert restored["summary"] == original["summary"]
    assert restored["stock_summary"] == original["stock_summary"]


@pytest.mark.integration
def test_graph_endpoint_limited_subgraph(api):
    r = api.get("/api/graph", params={"retailer_id": "R-112", "product_id": "P-05"})
    assert r.status_code == 200
    g = r.json()["graph"]
    assert 0 < len(g["nodes"]) < 60
    assert "INV-W-03-P-05" in g["highlighted_nodes"]
    assert api.get("/api/graph", params={"retailer_id": "bad", "product_id": "P-05"}).status_code == 422


@pytest.mark.integration
def test_dashboard_served(api):
    r = api.get("/")
    assert r.status_code == 200 and "ShelfSense" in r.text and "Simulated Demo Data" in r.text
    assert api.get("/static/app.js").status_code == 200

"""Integration tests: real FalkorDB, real Cypher, deterministic seed."""
from __future__ import annotations

import pytest

from app.db.seed import SCENARIOS
from app.services.investigation_service import InvestigationService
from app.services.mutation_service import MutationService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenarios_reach_expected_cause(seeded, scenario):
    r = InvestigationService(seeded).investigate(scenario_id=scenario["id"])
    assert r["probable_cause"]["code"] == scenario["expected_cause"]
    assert r["data_mode"] == "simulated"


def test_delayed_delivery_scenario_details(seeded):
    r = InvestigationService(seeded).investigate(scenario_id="A")
    pc = r["probable_cause"]
    assert (pc["status"], pc["confidence"]) == ("supported", "high")
    ids = {e["record_id"] for e in r["evidence"]}
    assert {"O-1012", "DEL-1012", "INV-W-01-P-01", "INV-R-104-P-01"} <= ids
    steps = {(s["from"], s["relationship"], s["to"]) for s in r["graph_path"]}
    assert ("R-104", "SERVED_BY", "D-02") in steps and ("DEL-1012", "FULFILLS", "O-1012") in steps
    assert any("DEL-1012" in a["action"] and "Konkan Trade Links" in a["action"] for a in r["recommended_actions"])


def test_missing_order_scenario(seeded):
    r = InvestigationService(seeded).investigate(scenario_id="B")
    assert r["probable_cause"]["status"] == "record_gap"
    assert any("Replenishment order" in m["item"] for m in r["missing_information"])
    assert "do not show who" in r["summary"]


def test_reserved_inventory_calculation(seeded):
    r = InvestigationService(seeded).investigate(scenario_id="C")
    route = {w["warehouse_id"]: w for w in r["stock_summary"]["route"]}
    assert (route["W-03"]["quantity"], route["W-03"]["reserved"], route["W-03"]["available"]) == (500, 480, 20)
    assert route["W-01"]["available"] == 420 - 70
    # Reservation holders are traced through RESERVES edges
    assert {"O-2113", "O-2115", "O-2119"} <= {e["record_id"] for e in r["evidence"]}
    assert any("W-01" in a["action"] and "O-2112" in a["action"] for a in r["recommended_actions"])
    assert not r["contradictions"]


def test_insufficient_evidence_scenario(seeded):
    r = InvestigationService(seeded).investigate(scenario_id="D")
    assert r["probable_cause"]["status"] == "undetermined"
    assert r["probable_cause"]["confidence"] == "low"
    assert "cannot" in r["summary"].lower() or "do not explain" in r["summary"].lower()
    items = " ".join(m["item"] for m in r["missing_information"])
    assert "W-02" in items and "O-2117" in items
    assert {o["warehouse_id"] for o in r["stock_summary"]["off_route"]} >= {"W-03"}


def test_facts_and_inferences_returned_separately(seeded):
    r = InvestigationService(seeded).investigate(scenario_id="A")
    assert r["observed_facts"] and r["inferences"]
    fact_ids = {f["id"] for f in r["observed_facts"]}
    assert all(f["id"].startswith("F") for f in r["observed_facts"])
    assert all(i["id"].startswith("I") for i in r["inferences"])
    assert all(set(i["based_on"]) <= fact_ids | {x["id"] for x in r["inferences"]} for i in r["inferences"])


def test_results_are_grounded_in_graph_records(seeded):
    """Every record ID cited by a fact or evidence card exists in FalkorDB with matching properties."""
    for sc in SCENARIOS:
        r = InvestigationService(seeded).investigate(scenario_id=sc["id"])
        cited = {rid for f in r["observed_facts"] for rid in f["record_ids"]} | {e["record_id"] for e in r["evidence"]}
        rows = seeded.read("MATCH (n) WHERE n.id IN $ids RETURN n.id", {"ids": sorted(cited)}).rows
        assert {row[0] for row in rows} == cited, sc["id"]
        for card in r["evidence"]:
            if card["entity_type"] == "Inventory":
                q = seeded.read("MATCH (i:Inventory {id: $id}) RETURN i.quantity, i.reserved_quantity",
                                {"id": card["record_id"]}).rows[0]
                assert q == [card["properties"]["quantity"], card["properties"]["reserved_quantity"]]
        # graph edges reference only returned nodes
        node_ids = {n["id"] for n in r["graph"]["nodes"]}
        assert all(e["source"] in node_ids and e["target"] in node_ids for e in r["graph"]["edges"])
        assert r["query_trace"] and all(t["cypher"] for t in r["query_trace"])


def test_delivery_change_changes_investigation(seeded):
    svc = InvestigationService(seeded)
    before = svc.investigate(scenario_id="A")
    assert before["probable_cause"]["code"] == "DELAYED_DELIVERY"

    m = MutationService(seeded).apply("Delivery", "DEL-1012", "status", "delivered", confirm=True)
    assert m["after"]["delivery"]["status"] == "delivered" and m["after"]["order"]["status"] == "delivered"

    after = svc.investigate(scenario_id="A")
    assert after["probable_cause"]["code"] == "DELIVERY_NOT_REFLECTED"
    assert "delayed" not in after["probable_cause"]["label"].lower()
    # Delivery does not silently update retailer inventory
    assert after["stock_summary"]["retailer"]["available"] == 0

    MutationService(seeded).apply("Inventory", "INV-R-104-P-01", "quantity", 48, confirm=True)
    final = svc.investigate(scenario_id="A")
    assert final["probable_cause"]["code"] == "NO_STOCKOUT"
    assert final["stock_summary"]["retailer"]["available"] == 48


def test_inventory_reservation_change_changes_investigation(seeded):
    svc = InvestigationService(seeded)
    MutationService(seeded).apply("Inventory", "INV-W-03-P-05", "reserved_quantity", 300, confirm=True)
    r = svc.investigate(scenario_id="C")
    assert r["probable_cause"]["code"] != "RESERVED_STOCK"
    # Changing the reserved count without releasing RESERVES links is flagged, not hidden
    assert any("INV-W-03-P-05" in c["statement"] for c in r["contradictions"])


def test_mutation_rejects_reserved_above_physical(seeded):
    from app.services.mutation_service import MutationError
    with pytest.raises(MutationError) as e:
        MutationService(seeded).apply("Inventory", "INV-W-03-P-05", "reserved_quantity", 900, confirm=True)
    assert e.value.code == "INCONSISTENT_VALUE"


def test_question_resolution_uses_names_and_graph_disambiguation(seeded):
    r = InvestigationService(seeded).investigate(question="Why is Surf Excel unavailable at Sharma Kirana Store?")
    assert (r["retailer"]["id"], r["product"]["id"]) == ("R-104", "P-01")
    assert "disambiguated" in r["resolved_by"]


def test_background_retailers_are_mostly_not_stocked_out(seeded):
    r = InvestigationService(seeded).investigate(retailer_id="R-101", product_id=
                                                 seeded.read("MATCH (:Retailer {id:'R-101'})-[:LISTS]->(p) RETURN p.id ORDER BY p.id LIMIT 1").rows[0][0])
    assert r["probable_cause"]["code"] == "NO_STOCKOUT"

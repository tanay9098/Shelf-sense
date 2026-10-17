"""Unit tests: evidence rules, validation and safety checks. No database involved."""
from __future__ import annotations

import copy

import pytest

from app.services import evidence_service as ev
from app.services.llm_service import validate_summary
from app.services.mutation_service import MutationError, _validate
from app.tools.investigation_tools import PRODUCT_ID, RETAILER_ID, InvalidIdentifier, validate_id

NOW = "2026-10-15T12:00:00"


def inv(iid, qty, reserved=0, captured="2026-10-15T08:00:00", loc="warehouse"):
    return {"id": iid, "quantity": qty, "reserved_quantity": reserved, "available_quantity": max(qty - reserved, 0),
            "captured_at": captured, "location_type": loc, "computed_available": max(qty - reserved, 0)}


def base_bundle(**over):
    b = {
        "now": NOW, "since": "2026-09-24T12:00:00", "lookback_days": 21,
        "retailer": {"id": "R-900", "name": "Test Kirana", "territory": "T", "location": "X"},
        "product": {"id": "P-90", "name": "Test Soap"},
        "listed": True,
        "retailer_stock": [inv("INV-R-900-P-90", 0, loc="retailer")],
        "network": [{"distributor": {"id": "D-90", "name": "Dist"}, "warehouse": {"id": "W-90", "name": "WH"},
                     "priority": 1, "inventory": inv("INV-W-90-P-90", 1000)}],
        "off_route": [], "orders": {"recent": [], "prior": None}, "reservations": [], "visits": [], "promotions": [],
    }
    b.update(over)
    return b


def order(oid, status, qty=40, delivery=None, warehouse=True):
    return {"order": {"id": oid, "quantity": qty, "status": status, "ordered_at": "2026-10-09T10:00:00",
                      "promised_at": "2026-10-12T18:00:00"},
            "distributor": {"id": "D-90", "name": "Dist"},
            "warehouse": {"id": "W-90", "name": "WH"} if warehouse else None,
            "delivery": delivery}


def test_delayed_delivery_is_supported_high():
    d = {"id": "DEL-9", "status": "delayed", "expected_at": "2026-10-12T18:00:00", "delivered_at": None}
    out = ev.analyse(base_bundle(orders={"recent": [order("O-9", "dispatched", delivery=d)], "prior": None}))
    assert out["probable_cause"]["code"] == "DELAYED_DELIVERY"
    assert out["probable_cause"]["confidence"] == "high"
    assert {"O-9", "DEL-9", "W-90", "INV-W-90-P-90"} <= set(out["path_ids"])


def test_overdue_in_transit_counts_as_delayed_even_without_delayed_flag():
    d = {"id": "DEL-9", "status": "in_transit", "expected_at": "2026-10-13T18:00:00", "delivered_at": None}
    out = ev.analyse(base_bundle(orders={"recent": [order("O-9", "dispatched", delivery=d)], "prior": None}))
    assert out["probable_cause"]["code"] == "DELAYED_DELIVERY"


def test_missing_expected_time_lowers_confidence():
    d = {"id": "DEL-9", "status": "delayed", "expected_at": None, "delivered_at": None}
    out = ev.analyse(base_bundle(orders={"recent": [order("O-9", "dispatched", delivery=d)], "prior": None}))
    assert out["probable_cause"]["confidence"] == "medium"


def test_no_order_is_record_gap_not_blame():
    out = ev.analyse(base_bundle())
    pc = out["probable_cause"]
    assert pc["code"] == "NO_REPLENISHMENT_ORDER" and pc["status"] == "record_gap"
    text = (out["summary"] + " ".join(m["why_it_matters"] for m in out["missing_information"])).lower()
    assert "not proof" in text or "do not show who" in text
    assert "failed to" not in text


def test_reserved_stock_physical_vs_available():
    w = inv("INV-W-90-P-90", 500, reserved=480)
    b = base_bundle(network=[{"distributor": {"id": "D-90", "name": "Dist"}, "warehouse": {"id": "W-90", "name": "WH"},
                              "priority": 1, "inventory": w}],
                    orders={"recent": [order("O-9", "pending_allocation", qty=60, warehouse=False)], "prior": None},
                    reservations=[{"order": {"id": "O-1"}, "inventory_id": "INV-W-90-P-90",
                                   "retailer": {"id": "R-1"}, "quantity": 480}])
    out = ev.analyse(b)
    assert out["probable_cause"]["code"] == "RESERVED_STOCK"
    assert ev.available(w) == 20
    assert any("500 physical" in f["statement"] and "20 available" in f["statement"] for f in out["observed_facts"])
    assert not out["contradictions"]


def test_available_quantity_is_never_negative():
    assert ev.available({"quantity": 5, "reserved_quantity": 9}) == 0


def test_reservation_mismatch_is_reported_as_contradiction():
    w = inv("INV-W-90-P-90", 500, reserved=480)
    b = base_bundle(network=[{"distributor": {"id": "D-90", "name": "Dist"}, "warehouse": {"id": "W-90", "name": "WH"},
                              "priority": 1, "inventory": w}])
    out = ev.analyse(b)  # no RESERVES links returned for 480 reserved units
    assert any("reserved_quantity=480" in c["statement"] for c in out["contradictions"])


def test_insufficient_evidence_is_undetermined_low():
    b = base_bundle(network=[{"distributor": {"id": "D-90", "name": "Dist"}, "warehouse": {"id": "W-90", "name": "WH"},
                              "priority": 1, "inventory": None}],
                    orders={"recent": [order("O-9", "cancelled", warehouse=False)], "prior": None})
    out = ev.analyse(b)
    assert out["probable_cause"]["code"] == "UNDETERMINED"
    assert out["probable_cause"]["confidence"] == "low"
    items = " ".join(m["item"] for m in out["missing_information"])
    assert "Inventory record for P-90 at W-90" in items and "Cancellation reason for O-9" in items


def test_delivered_after_snapshot_is_not_assumed_to_update_inventory():
    d = {"id": "DEL-9", "status": "delivered", "expected_at": "2026-10-12T18:00:00", "delivered_at": "2026-10-15T11:00:00"}
    out = ev.analyse(base_bundle(orders={"recent": [order("O-9", "delivered", delivery=d)], "prior": None}))
    assert out["probable_cause"]["code"] == "DELIVERY_NOT_REFLECTED"
    assert out["probable_cause"]["status"] == "hypothesis"


def test_stock_available_means_no_stockout():
    out = ev.analyse(base_bundle(retailer_stock=[inv("INV-R-900-P-90", 12, loc="retailer")]))
    assert out["probable_cause"]["code"] == "NO_STOCKOUT"


def test_facts_and_inferences_are_separate_and_inferences_cite_facts():
    d = {"id": "DEL-9", "status": "delayed", "expected_at": "2026-10-12T18:00:00", "delivered_at": None}
    out = ev.analyse(base_bundle(orders={"recent": [order("O-9", "dispatched", delivery=d)], "prior": None}))
    fact_ids = {f["id"] for f in out["observed_facts"]}
    inf_ids = {i["id"] for i in out["inferences"]}
    assert fact_ids and inf_ids and not (fact_ids & inf_ids)
    for i in out["inferences"]:
        assert i["based_on"], i
        assert all(ref in fact_ids or ref in inf_ids for ref in i["based_on"])


def test_facts_only_cite_records_present_in_input():
    d = {"id": "DEL-9", "status": "delayed", "expected_at": "2026-10-12T18:00:00", "delivered_at": None}
    b = base_bundle(orders={"recent": [order("O-9", "dispatched", delivery=d)], "prior": None})
    known = {"R-900", "P-90", "D-90", "W-90", "INV-W-90-P-90", "INV-R-900-P-90", "O-9", "DEL-9"}
    out = ev.analyse(copy.deepcopy(b))
    for f in out["observed_facts"]:
        assert set(f["record_ids"]) <= known


@pytest.mark.parametrize("value", ["R-104", "R-001"])
def test_valid_retailer_ids(value):
    assert validate_id(value, RETAILER_ID, "retailer") == value


@pytest.mark.parametrize("value", ["R-1", "r-104", "R-104'; MATCH (n) DETACH DELETE n //", "", "P-01", 104, None])
def test_invalid_retailer_ids(value):
    with pytest.raises(InvalidIdentifier):
        validate_id(value, RETAILER_ID, "retailer")


def test_invalid_product_id():
    with pytest.raises(InvalidIdentifier):
        validate_id("P-1x", PRODUCT_ID, "product")


@pytest.mark.parametrize("entity,field,value,code", [
    ("Delivery", "status", "teleported", "INVALID_VALUE"),
    ("Delivery", "notes", "x", "FIELD_NOT_ALLOWED"),
    ("Inventory", "quantity", -1, "INVALID_VALUE"),
    ("Inventory", "quantity", 1.5, "INVALID_VALUE"),
    ("Inventory", "quantity", True, "INVALID_VALUE"),
    ("Inventory", "quantity", 10**9, "INVALID_VALUE"),
    ("Order", "status", "delivered", "FIELD_NOT_ALLOWED"),
])
def test_mutation_allowlist_rejects(entity, field, value, code):
    with pytest.raises(MutationError) as e:
        _validate(entity, field, value)
    assert e.value.code == code


def test_llm_summary_validator_rejects_invented_ids():
    payload = {"probable_cause": {"status": "supported"}, "facts": ["Order O-1012 linked to DEL-1012"]}
    assert validate_summary("Delivery DEL-1012 for O-1012 is late.", payload)[0]
    ok, reason = validate_summary("Delivery DEL-7777 is late.", payload)
    assert not ok and "DEL-7777" in reason


def test_llm_summary_validator_preserves_undetermined():
    payload = {"probable_cause": {"status": "undetermined"}}
    assert not validate_summary("The stockout was caused by a strike.", payload)[0]
    assert validate_summary("The cause cannot be determined from the records.", payload)[0]

"""Allow-listed demo mutations. No arbitrary properties, labels or Cypher.

Each allowed (entity, field) pair maps to a fixed Cypher template and a validator.
State changes are kept internally consistent:
  * Delivery.status -> also updates delivered_at and the linked Order.status
  * Inventory.quantity / reserved_quantity -> recomputes available_quantity, stamps captured_at
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.config import Settings, get_settings
from app.db.connection import GraphClient

DELIVERY_STATUSES = ["scheduled", "dispatched", "in_transit", "delayed", "delivered", "failed"]
ORDER_STATUS_FOR_DELIVERY = {
    "scheduled": "allocated",
    "dispatched": "dispatched",
    "in_transit": "dispatched",
    "delayed": "dispatched",
    "delivered": "delivered",
    "failed": "dispatched",
}
MAX_QTY = 100_000

ALLOWLIST = {
    "Delivery": {"status": {"type": "enum", "values": DELIVERY_STATUSES}},
    "Inventory": {"quantity": {"type": "int", "min": 0, "max": MAX_QTY},
                  "reserved_quantity": {"type": "int", "min": 0, "max": MAX_QTY}},
}


class MutationError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


Q_GET_DELIVERY = """
MATCH (del:Delivery {id: $id}) OPTIONAL MATCH (del)-[:FULFILLS]->(o:Order)
RETURN del, o
"""
Q_SET_DELIVERY = """
MATCH (del:Delivery {id: $id})
SET del.status = $status, del.delivered_at = $delivered_at
WITH del
OPTIONAL MATCH (del)-[:FULFILLS]->(o:Order)
SET o.status = $order_status
RETURN del, o
"""
Q_GET_INVENTORY = "MATCH (i:Inventory {id: $id}) RETURN i"
Q_SET_INVENTORY = """
MATCH (i:Inventory {id: $id})
SET i.quantity = $quantity, i.reserved_quantity = $reserved,
    i.available_quantity = $available, i.captured_at = $captured_at
RETURN i
"""


def describe_allowlist() -> dict:
    return {"allowed": ALLOWLIST,
            "notes": ["Marking a delivery 'delivered' stamps delivered_at and sets the linked order to 'delivered'. "
                      "It does NOT change retailer inventory - that must be recounted separately.",
                      "Editing inventory recomputes available_quantity = quantity − reserved_quantity and stamps captured_at."]}


def _validate(entity: str, field: str, value):
    spec = ALLOWLIST.get(entity, {}).get(field)
    if spec is None:
        raise MutationError("FIELD_NOT_ALLOWED", f"{entity}.{field} cannot be modified in the demo.")
    if spec["type"] == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            raise MutationError("INVALID_VALUE", f"{entity}.{field} must be one of: {', '.join(spec['values'])}.")
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        else:
            raise MutationError("INVALID_VALUE", f"{entity}.{field} must be a whole number.")
    if not spec["min"] <= value <= spec["max"]:
        raise MutationError("INVALID_VALUE", f"{entity}.{field} must be between {spec['min']} and {spec['max']}.")
    return value


class MutationService:
    def __init__(self, client: GraphClient, settings: Settings | None = None):
        self.client = client
        self.settings = settings or get_settings()
        now = datetime.fromisoformat(self.settings.demo_now)
        # Deterministic demo timestamps: delivery lands 1h before the demo clock, recount 30 min before.
        self.delivered_stamp = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        self.recount_stamp = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")

    def apply(self, entity: str, record_id: str, field: str, value, confirm: bool) -> dict:
        value = _validate(entity, field, value)
        if not confirm:
            raise MutationError("CONFIRMATION_REQUIRED", "Set confirm=true to modify the simulated dataset.", 400)
        if entity == "Delivery":
            return self._delivery(record_id, value)
        return self._inventory(record_id, field, value)

    def _delivery(self, record_id: str, status: str) -> dict:
        rows = self.client.read(Q_GET_DELIVERY, {"id": record_id}).rows
        if not rows:
            raise MutationError("RECORD_NOT_FOUND", f"Delivery {record_id} was not found.", 404)
        before = {"delivery": dict(rows[0][0].properties),
                  "order": dict(rows[0][1].properties) if rows[0][1] is not None else None}
        delivered_at = before["delivery"].get("delivered_at") if status == "delivered" else None
        if status == "delivered" and not delivered_at:
            delivered_at = self.delivered_stamp
        out = self.client.write(Q_SET_DELIVERY, {"id": record_id, "status": status, "delivered_at": delivered_at,
                                                 "order_status": ORDER_STATUS_FOR_DELIVERY[status]}).rows
        after = {"delivery": dict(out[0][0].properties),
                 "order": dict(out[0][1].properties) if out[0][1] is not None else None}
        return {"entity_type": "Delivery", "record_id": record_id, "field": "status",
                "before": before, "after": after, "status": "applied",
                "side_effects": [f"Linked order status set to '{ORDER_STATUS_FOR_DELIVERY[status]}'",
                                 f"delivered_at = {delivered_at}"]}

    def _inventory(self, record_id: str, field: str, value: int) -> dict:
        rows = self.client.read(Q_GET_INVENTORY, {"id": record_id}).rows
        if not rows:
            raise MutationError("RECORD_NOT_FOUND", f"Inventory {record_id} was not found.", 404)
        before = dict(rows[0][0].properties)
        qty = value if field == "quantity" else int(before["quantity"])
        reserved = value if field == "reserved_quantity" else int(before["reserved_quantity"])
        if reserved > qty:
            raise MutationError("INCONSISTENT_VALUE",
                                f"Reserved quantity ({reserved}) cannot exceed physical quantity ({qty}).")
        out = self.client.write(Q_SET_INVENTORY, {"id": record_id, "quantity": qty, "reserved": reserved,
                                                  "available": qty - reserved, "captured_at": self.recount_stamp}).rows
        return {"entity_type": "Inventory", "record_id": record_id, "field": field,
                "before": before, "after": dict(out[0][0].properties), "status": "applied",
                "side_effects": [f"available_quantity recomputed = {qty - reserved}",
                                 f"captured_at = {self.recount_stamp}"]}

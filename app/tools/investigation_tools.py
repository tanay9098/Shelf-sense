"""Approved investigation tools.

Every tool is a fixed, parameterised Cypher template. Nothing here concatenates user
or LLM text into a query. Each tool returns:
  * `data`   - normalised dicts used by the evidence engine
  * a trace entry (tool, cypher, params, rows, duration)
  * graph elements (nodes/edges) taken from the *returned* Node/Edge objects, which
    are what the dashboard visualises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from falkordb.edge import Edge
from falkordb.node import Node
from falkordb.path import Path

from app.db.connection import GraphClient

RETAILER_ID = re.compile(r"^R-\d{3}$")
PRODUCT_ID = re.compile(r"^P-\d{2}$")
RECORD_ID = re.compile(r"^[A-Z]{1,3}-[A-Z0-9-]{2,20}$")


class InvalidIdentifier(ValueError):
    pass


def validate_id(value: str, pattern: re.Pattern, kind: str) -> str:
    if not isinstance(value, str) or len(value) > 32 or not pattern.match(value):
        raise InvalidIdentifier(f"'{str(value)[:32]}' is not a valid {kind} ID.")
    return value


# --------------------------------------------------------------------------- graph collector
@dataclass
class GraphCollector:
    """Accumulates the subgraph touched by investigation queries."""

    nodes: dict[str, dict] = field(default_factory=dict)          # business id -> node
    _internal: dict[int, str] = field(default_factory=dict)       # FalkorDB internal id -> business id
    _pending_edges: list[tuple[int, str, int, dict]] = field(default_factory=list)

    def ingest_value(self, value: Any) -> None:
        if isinstance(value, Node):
            props = dict(value.properties or {})
            bid = props.get("id")
            if bid is None:
                return
            self._internal[value.id] = bid
            label = value.labels[0] if value.labels else "Node"
            if bid not in self.nodes:
                self.nodes[bid] = {"id": bid, "label": label, "properties": props}
            else:
                self.nodes[bid]["properties"].update(props)
        elif isinstance(value, Edge):
            self._pending_edges.append((value.src_node, value.relation, value.dest_node, dict(value.properties or {})))
        elif isinstance(value, Path):
            for n in value.nodes():
                self.ingest_value(n)
            for e in value.edges():
                self.ingest_value(e)
        elif isinstance(value, list):
            for v in value:
                self.ingest_value(v)

    def ingest_rows(self, rows: list[list[Any]]) -> None:
        for row in rows:
            for v in row:
                self.ingest_value(v)

    def edges(self) -> list[dict]:
        out: dict[str, dict] = {}
        for src, rel, dst, props in self._pending_edges:
            s, d = self._internal.get(src), self._internal.get(dst)
            if s is None or d is None:
                continue  # endpoint not returned by any query -> not drawn
            key = f"{s}|{rel}|{d}"
            out[key] = {"id": key, "source": s, "target": d, "type": rel, "properties": props}
        return list(out.values())


def _props(node: Node | None) -> dict | None:
    return dict(node.properties) if isinstance(node, Node) else None


# --------------------------------------------------------------------------- tool runner
@dataclass
class ToolContext:
    client: GraphClient
    collector: GraphCollector = field(default_factory=GraphCollector)
    trace: list[dict] = field(default_factory=list)

    def run(self, tool: str, cypher: str, params: dict, purpose: str):
        outcome = self.client.read(cypher, params)
        self.collector.ingest_rows(outcome.rows)
        self.trace.append({
            "tool": tool,
            "purpose": purpose,
            "cypher": " ".join(cypher.split()),
            "params": params,
            "rows_returned": len(outcome.rows),
            "duration_ms": outcome.duration_ms,
        })
        return outcome.rows


# --------------------------------------------------------------------------- Cypher templates
Q_RESOLVE = """
OPTIONAL MATCH (r:Retailer {id: $retailer_id})
OPTIONAL MATCH (p:Product {id: $product_id})
OPTIONAL MATCH (r)-[l:LISTS]->(p)
RETURN r, p, l
"""

Q_RETAILER_STOCK = """
MATCH (r:Retailer {id: $retailer_id})-[h:HOLDS]->(i:Inventory)-[o:OF_PRODUCT]->(p:Product {id: $product_id})
RETURN r, h, i, o, p,
       CASE WHEN i.quantity - i.reserved_quantity < 0 THEN 0 ELSE i.quantity - i.reserved_quantity END AS computed_available
ORDER BY i.captured_at DESC
LIMIT 5
"""

# 4-hop traversal: retailer -> distributor -> warehouse -> inventory -> product
Q_SUPPLY_NETWORK = """
MATCH (r:Retailer {id: $retailer_id})-[sb:SERVED_BY]->(d:Distributor)-[sf:SOURCES_FROM]->(w:Warehouse)
OPTIONAL MATCH (w)-[h:HOLDS]->(i:Inventory)-[o:OF_PRODUCT]->(p:Product {id: $product_id})
RETURN r, sb, d, sf, w, h, i, o, p, sf.priority AS priority,
       CASE WHEN i IS NULL THEN null
            WHEN i.quantity - i.reserved_quantity < 0 THEN 0
            ELSE i.quantity - i.reserved_quantity END AS computed_available
ORDER BY d.id, priority ASC
LIMIT 25
"""

# Warehouses holding available stock of the product that are NOT on any route serving the retailer
Q_OFF_ROUTE_STOCK = """
MATCH (r:Retailer {id: $retailer_id})
MATCH (w:Warehouse)-[h:HOLDS]->(i:Inventory)-[o:OF_PRODUCT]->(p:Product {id: $product_id})
WHERE NOT (r)-[:SERVED_BY]->(:Distributor)-[:SOURCES_FROM]->(w)
  AND i.quantity - i.reserved_quantity > 0
RETURN w, h, i, o, p, i.quantity - i.reserved_quantity AS computed_available
ORDER BY computed_available DESC
LIMIT 10
"""

Q_ORDERS_RECENT = """
MATCH (o:Order)-[fr:FOR_RETAILER]->(r:Retailer {id: $retailer_id}),
      (o)-[fp:FOR_PRODUCT]->(p:Product {id: $product_id})
WHERE o.ordered_at >= $since
OPTIONAL MATCH (o)-[at:ASSIGNED_TO]->(d:Distributor)
OPTIONAL MATCH (o)-[af:ALLOCATED_FROM]->(w:Warehouse)
OPTIONAL MATCH (del:Delivery)-[f:FULFILLS]->(o)
RETURN o, fr, r, fp, p, at, d, af, w, del, f
ORDER BY o.ordered_at DESC
LIMIT 20
"""

Q_ORDER_LAST_BEFORE = """
MATCH (o:Order)-[fr:FOR_RETAILER]->(r:Retailer {id: $retailer_id}),
      (o)-[fp:FOR_PRODUCT]->(p:Product {id: $product_id})
WHERE o.ordered_at < $since
OPTIONAL MATCH (del:Delivery)-[f:FULFILLS]->(o)
RETURN o, fr, r, fp, p, del, f
ORDER BY o.ordered_at DESC
LIMIT 1
"""

Q_RESERVATIONS = """
MATCH (o:Order)-[rs:RESERVES]->(i:Inventory)
WHERE i.id IN $inventory_ids
OPTIONAL MATCH (o)-[fr:FOR_RETAILER]->(r:Retailer)
RETURN o, rs, i, fr, r, rs.quantity AS reserved
ORDER BY reserved DESC
LIMIT 25
"""

Q_SALES_VISITS = """
MATCH (v:SalesVisit)-[a:AT_RETAILER]->(r:Retailer {id: $retailer_id})
WHERE v.visited_at >= $since
OPTIONAL MATCH (v)-[ob:OBSERVED]->(p:Product {id: $product_id})
RETURN v, a, r, ob, p, ob.shelf_status AS shelf_status
ORDER BY v.visited_at DESC
LIMIT 10
"""

Q_PROMOTIONS = """
MATCH (pr:Promotion)-[pm:PROMOTES]->(p:Product {id: $product_id})
WHERE pr.start_date <= $today AND pr.end_date >= $today
  AND (pr.territory = $territory OR pr.territory = 'All')
RETURN pr, pm, p
LIMIT 10
"""


# --------------------------------------------------------------------------- tools
def resolve_entities(ctx: ToolContext, retailer_id: str, product_id: str) -> dict:
    rows = ctx.run("resolve_entities", Q_RESOLVE,
                   {"retailer_id": retailer_id, "product_id": product_id},
                   "Confirm the retailer and product exist and whether the product is listed")
    r, p, l = rows[0] if rows else (None, None, None)
    return {"retailer": _props(r), "product": _props(p), "listed": l is not None,
            "listed_since": (l.properties or {}).get("since") if isinstance(l, Edge) else None}


def get_retailer_stock(ctx: ToolContext, retailer_id: str, product_id: str) -> list[dict]:
    rows = ctx.run("get_retailer_stock", Q_RETAILER_STOCK,
                   {"retailer_id": retailer_id, "product_id": product_id},
                   "Read the retailer's own stock snapshot for the product")
    out = []
    for row in rows:
        inv = _props(row[2])
        inv["computed_available"] = row[5]
        out.append(inv)
    return out


def trace_supply_network(ctx: ToolContext, retailer_id: str, product_id: str) -> list[dict]:
    rows = ctx.run("trace_supply_network", Q_SUPPLY_NETWORK,
                   {"retailer_id": retailer_id, "product_id": product_id},
                   "Traverse Retailer→Distributor→Warehouse→Inventory→Product replenishment routes")
    out = []
    for row in rows:
        inv = _props(row[6])
        if inv is not None:
            inv["computed_available"] = row[10]
        out.append({
            "distributor": _props(row[2]),
            "warehouse": _props(row[4]),
            "priority": row[9],
            "inventory": inv,
        })
    return out


def find_off_route_stock(ctx: ToolContext, retailer_id: str, product_id: str) -> list[dict]:
    rows = ctx.run("find_off_route_stock", Q_OFF_ROUTE_STOCK,
                   {"retailer_id": retailer_id, "product_id": product_id},
                   "Find warehouses with available stock that no recorded route connects to this retailer")
    out = []
    for row in rows:
        inv = _props(row[2])
        inv["computed_available"] = row[5]
        out.append({"warehouse": _props(row[0]), "inventory": inv})
    return out


def trace_order_fulfillment(ctx: ToolContext, retailer_id: str, product_id: str, since: str) -> dict:
    params = {"retailer_id": retailer_id, "product_id": product_id, "since": since}
    rows = ctx.run("trace_order_fulfillment", Q_ORDERS_RECENT, params,
                   "Trace recent orders and their linked distributor, warehouse and delivery")
    recent = []
    for row in rows:
        recent.append({
            "order": _props(row[0]),
            "distributor": _props(row[6]),
            "warehouse": _props(row[8]),
            "delivery": _props(row[9]),
        })
    prior_rows = ctx.run("last_order_before_window", Q_ORDER_LAST_BEFORE, params,
                         "Find the most recent order before the lookback window (context only)")
    prior = None
    if prior_rows:
        prior = {"order": _props(prior_rows[0][0]), "delivery": _props(prior_rows[0][5])}
    return {"recent": recent, "prior": prior}


def inspect_reservations(ctx: ToolContext, inventory_ids: list[str]) -> list[dict]:
    if not inventory_ids:
        return []
    rows = ctx.run("inspect_reservations", Q_RESERVATIONS, {"inventory_ids": inventory_ids[:10]},
                   "List orders holding reservations on the route warehouse stock")
    return [{"order": _props(row[0]), "inventory_id": row[2].properties.get("id"),
             "retailer": _props(row[4]), "quantity": row[5]} for row in rows]


def inspect_sales_visits(ctx: ToolContext, retailer_id: str, product_id: str, since: str) -> list[dict]:
    rows = ctx.run("inspect_sales_visits", Q_SALES_VISITS,
                   {"retailer_id": retailer_id, "product_id": product_id, "since": since},
                   "Read recent field visits and any shelf observation for the product")
    return [{"visit": _props(row[0]), "observed_product": row[4] is not None, "shelf_status": row[5]} for row in rows]


def inspect_active_promotions(ctx: ToolContext, product_id: str, territory: str, today: str) -> list[dict]:
    rows = ctx.run("inspect_active_promotions", Q_PROMOTIONS,
                   {"product_id": product_id, "territory": territory, "today": today},
                   "Check active promotions on the product in the retailer's territory")
    return [_props(row[0]) for row in rows]


TOOL_CATALOGUE = [
    {"name": "resolve_entities", "description": "Validate retailer/product and assortment listing"},
    {"name": "get_retailer_stock", "description": "Retailer stock snapshot (physical vs available)"},
    {"name": "trace_supply_network", "description": "Multi-hop route Retailer→Distributor→Warehouse→Inventory"},
    {"name": "find_off_route_stock", "description": "Stock that exists but is not reachable via recorded routes"},
    {"name": "trace_order_fulfillment", "description": "Orders with linked distributor, warehouse, delivery"},
    {"name": "inspect_reservations", "description": "Orders holding reservations on route stock"},
    {"name": "inspect_sales_visits", "description": "Field visits and shelf observations"},
    {"name": "inspect_active_promotions", "description": "Active promotions affecting demand"},
]

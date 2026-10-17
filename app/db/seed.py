"""Deterministic, idempotent seed for the ShelfSense demo graph.

All data is SIMULATED. Retailers, distributors, warehouses, orders and incidents are
fictional. "Surf Excel" appears only as an illustrative product name; nothing here
describes a real event involving Hindustan Unilever or any other company.

Running `reset_graph()` deletes the graph and rebuilds exactly the same data every time
(fixed random seed, fixed timestamps anchored to SEED_NOW).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.db.connection import GraphClient, GraphMissing
from app.db.schema import INDEX_STATEMENTS

SEED_NOW = datetime(2026, 10, 15, 12, 0, 0)  # matches default DEMO_NOW
RANDOM_SEED = 2026
SEED_VERSION = "2026.10-a"


def ts(days: float = 0, hours: float = 0) -> str:
    """ISO timestamp relative to SEED_NOW (negative = past)."""
    return (SEED_NOW + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- masters
DISTRIBUTORS = [
    {"id": "D-01", "name": "Sahyadri Distributors", "territory": "Pune"},
    {"id": "D-02", "name": "Konkan Trade Links", "territory": "Mumbai West"},
    {"id": "D-03", "name": "Harbour FMCG Partners", "territory": "Navi Mumbai"},
]

WAREHOUSES = [
    {"id": "W-01", "name": "Bhiwandi DC", "territory": "Mumbai West"},
    {"id": "W-02", "name": "Chakan DC", "territory": "Pune"},
    {"id": "W-03", "name": "Taloja DC", "territory": "Navi Mumbai"},
]

# distributor -> [(warehouse, priority)]
ROUTES = {
    "D-01": [("W-02", 1)],
    "D-02": [("W-01", 1)],
    "D-03": [("W-03", 1), ("W-01", 2)],
}

PRODUCTS = [
    {"id": "P-01", "name": "Surf Excel Easy Wash 1kg", "brand": "Surf Excel", "category": "Detergent", "pack_size": "1 kg"},
    {"id": "P-02", "name": "Surf Excel Matic Liquid 1L", "brand": "Surf Excel", "category": "Detergent", "pack_size": "1 L"},
    {"id": "P-03", "name": "Kesari Gold Chakki Atta 5kg", "brand": "Kesari Gold", "category": "Staples", "pack_size": "5 kg"},
    {"id": "P-04", "name": "Neelgiri Premium Tea 500g", "brand": "Neelgiri", "category": "Beverages", "pack_size": "500 g"},
    {"id": "P-05", "name": "Sparkle Glow Soap 4x100g", "brand": "Sparkle Glow", "category": "Personal Care", "pack_size": "4 x 100 g"},
    {"id": "P-06", "name": "Dentofresh Toothpaste 150g", "brand": "Dentofresh", "category": "Oral Care", "pack_size": "150 g"},
    {"id": "P-07", "name": "Crispo Salted Chips 52g", "brand": "Crispo", "category": "Snacks", "pack_size": "52 g"},
    {"id": "P-08", "name": "Shuddh Sunflower Oil 1L", "brand": "Shuddh", "category": "Edible Oil", "pack_size": "1 L"},
    {"id": "P-09", "name": "Masala Magic Noodles 4-pack", "brand": "Masala Magic", "category": "Packaged Food", "pack_size": "4 x 70 g"},
    {"id": "P-10", "name": "Glowa Dishwash Bar 500g", "brand": "Glowa", "category": "Home Care", "pack_size": "500 g"},
    {"id": "P-11", "name": "CocoPure Hair Oil 200ml", "brand": "CocoPure", "category": "Personal Care", "pack_size": "200 ml"},
    {"id": "P-12", "name": "Choco Crunch Biscuits 120g", "brand": "Choco Crunch", "category": "Biscuits", "pack_size": "120 g"},
]

_RETAILER_ROWS = [
    # id, name, territory, location, distributor
    ("R-101", "Mehta Super Mart", "Mumbai West", "Andheri West", "D-02"),
    ("R-102", "Fernandes Provision Store", "Mumbai West", "Bandra", "D-02"),
    ("R-103", "Joshi General Stores", "Mumbai West", "Goregaon", "D-02"),
    ("R-104", "Sharma Kirana Store", "Mumbai West", "Malad West", "D-02"),
    ("R-105", "New Bombay Bazaar", "Mumbai West", "Borivali", "D-02"),
    ("R-106", "Shree Ganesh Traders", "Mumbai West", "Kandivali", "D-02"),
    ("R-107", "Patel Daily Needs", "Mumbai West", "Jogeshwari", "D-02"),
    ("R-108", "Kulkarni Kirana", "Pune", "Kothrud", "D-01"),
    ("R-109", "Deshmukh Supermarket", "Pune", "Aundh", "D-01"),
    ("R-110", "Pawar Provision Centre", "Pune", "Hadapsar", "D-01"),
    ("R-111", "Annapurna Stores", "Pune", "Baner", "D-01"),
    ("R-112", "Sai Krupa Mart", "Navi Mumbai", "Vashi", "D-03"),
    ("R-113", "Harbour Fresh Bazaar", "Navi Mumbai", "Nerul", "D-03"),
    ("R-114", "Gupta Kirana & Sons", "Navi Mumbai", "Kharghar", "D-03"),
    ("R-115", "Royal Super Store", "Navi Mumbai", "Belapur", "D-03"),
    ("R-116", "Shinde General Stores", "Pune", "Wakad", "D-01"),
    ("R-117", "Lokmanya Kirana", "Pune", "Shivajinagar", "D-01"),
    ("R-118", "Bhosale Mini Mart", "Pune", "Viman Nagar", "D-01"),
    ("R-119", "Seawoods Daily Mart", "Navi Mumbai", "Seawoods", "D-03"),
    ("R-120", "Ulwe Family Store", "Navi Mumbai", "Ulwe", "D-03"),
]
RETAILERS = [
    {"id": r[0], "name": r[1], "territory": r[2], "location": r[3]} for r in _RETAILER_ROWS
]
RETAILER_DISTRIBUTOR = {r[0]: r[4] for r in _RETAILER_ROWS}

PROMOTIONS = [
    {"id": "PR-01", "name": "Festive Wash Fest", "product": "P-01", "territory": "Mumbai West",
     "start_date": "2026-10-01", "end_date": "2026-10-20", "status": "active",
     "mechanic": "Buy 2 get 10% off"},
    {"id": "PR-02", "name": "Glow Bonanza Bulk Scheme", "product": "P-05", "territory": "Navi Mumbai",
     "start_date": "2026-10-08", "end_date": "2026-10-25", "status": "active",
     "mechanic": "Retailer bulk-buy slab discount"},
    {"id": "PR-03", "name": "Monsoon Snack Saver", "product": "P-12", "territory": "All",
     "start_date": "2026-09-01", "end_date": "2026-09-30", "status": "ended",
     "mechanic": "Rs 5 off"},
    {"id": "PR-04", "name": "Diwali Kitchen Combo", "product": "P-08", "territory": "Pune",
     "start_date": "2026-11-01", "end_date": "2026-11-15", "status": "planned",
     "mechanic": "Combo with P-03"},
]

# --------------------------------------------------------------------------- scenarios
SCENARIOS = [
    {
        "id": "A",
        "title": "Stock in warehouse, delivery delayed",
        "retailer_id": "R-104",
        "product_id": "P-01",
        "question": "Why is Surf Excel Easy Wash 1kg unavailable at Sharma Kirana Store (R-104) even though Bhiwandi DC has sufficient inventory?",
        "expected_cause": "DELAYED_DELIVERY",
        "teaser": "Retailer shelf is empty, W-01 holds 1,000 available units, the linked shipment is late.",
    },
    {
        "id": "B",
        "title": "No replenishment order on record",
        "retailer_id": "R-108",
        "product_id": "P-03",
        "question": "Why is Kesari Gold Atta out of stock at Kulkarni Kirana (R-108)?",
        "expected_cause": "NO_REPLENISHMENT_ORDER",
        "teaser": "Network stock is available, but no order links the retailer to it.",
    },
    {
        "id": "C",
        "title": "Physical stock exists, but it is reserved",
        "retailer_id": "R-112",
        "product_id": "P-05",
        "question": "Taloja DC shows 500 units of Sparkle Glow Soap - why can't Sai Krupa Mart (R-112) get any?",
        "expected_cause": "RESERVED_STOCK",
        "teaser": "500 physical units, 480 reserved by other orders - only 20 available.",
    },
    {
        "id": "D",
        "title": "Insufficient evidence",
        "retailer_id": "R-117",
        "product_id": "P-07",
        "question": "Why does Lokmanya Kirana (R-117) have no Crispo Salted Chips?",
        "expected_cause": "UNDETERMINED",
        "teaser": "Stale stock count, a cancelled order with no reason, no route inventory record.",
    },
    {
        "id": "E",
        "title": "Order dispatched, delivery record missing",
        "retailer_id": "R-106",
        "product_id": "P-06",
        "question": "Dentofresh Toothpaste is missing at Shree Ganesh Traders (R-106) - what happened to the order?",
        "expected_cause": "MISSING_DELIVERY_RECORD",
        "teaser": "The order says dispatched, but no delivery record is linked to it.",
    },
]
SCENARIO_PAIRS = {(s["retailer_id"], s["product_id"]) for s in SCENARIOS}


def _build_dataset() -> dict:
    rng = random.Random(RANDOM_SEED)
    retailer_inventory: list[dict] = []
    warehouse_inventory: dict[tuple[str, str], dict] = {}
    listings: list[dict] = []
    orders: list[dict] = []
    deliveries: list[dict] = []
    reservations: list[dict] = []  # {order, inventory, quantity}
    visits: list[dict] = []

    # ---- warehouse inventory (background), scenario overrides below
    for w in WAREHOUSES:
        for p in PRODUCTS:
            if w["id"] == "W-02" and p["id"] == "P-07":
                continue  # Scenario D: no inventory record on the route warehouse
            warehouse_inventory[(w["id"], p["id"])] = {
                "id": f"INV-{w['id']}-{p['id']}",
                "quantity": rng.randrange(300, 1500, 10),
                "reserved_quantity": 0,
                "captured_at": ts(hours=-6),
                "location_type": "warehouse",
                "warehouse": w["id"],
                "product": p["id"],
            }
    overrides = {
        ("W-01", "P-01"): 1200,  # Scenario A: plenty of physical stock
        ("W-02", "P-03"): 900,   # Scenario B
        ("W-03", "P-05"): 500,   # Scenario C: physical stock, mostly reserved
        ("W-01", "P-05"): 420,   # Scenario C alternative source (priority 2 route)
        ("W-03", "P-07"): 900,   # Scenario D: off-route stock
        ("W-01", "P-06"): 640,   # Scenario E
    }
    for key, qty in overrides.items():
        warehouse_inventory[key]["quantity"] = qty

    # ---- listings + retailer stock
    for r in RETAILERS:
        listed = set(rng.sample([p["id"] for p in PRODUCTS], 7))
        listed |= {pid for (rid, pid) in SCENARIO_PAIRS if rid == r["id"]}
        for pid in sorted(listed):
            listings.append({"retailer": r["id"], "product": pid, "since": "2025-04-01"})
            qty = 0 if (r["id"], pid) in SCENARIO_PAIRS else rng.randint(6, 72)
            captured = ts(hours=-4)
            if (r["id"], pid) == ("R-117", "P-07"):
                captured = ts(days=-13, hours=-2)  # Scenario D: stale count
            retailer_inventory.append({
                "id": f"INV-{r['id']}-{pid}",
                "quantity": qty,
                "reserved_quantity": 0,
                "captured_at": captured,
                "location_type": "retailer",
                "retailer": r["id"],
                "product": pid,
            })

    def add_order(oid, rid, pid, qty, status, ordered_at, promised_at, warehouse=None, **extra):
        orders.append({
            "id": oid, "retailer": rid, "product": pid, "distributor": RETAILER_DISTRIBUTOR[rid],
            "warehouse": warehouse, "quantity": qty, "status": status,
            "ordered_at": ordered_at, "promised_at": promised_at,
            "cancel_reason": extra.get("cancel_reason"),
        })

    def add_delivery(oid, status, dispatched_at, expected_at, delivered_at=None, note=None):
        deliveries.append({
            "id": "DEL-" + oid.split("-", 1)[1], "order": oid, "status": status,
            "dispatched_at": dispatched_at, "expected_at": expected_at,
            "delivered_at": delivered_at, "note": note,
        })

    def reserve(oid, wid, pid, qty):
        inv = warehouse_inventory[(wid, pid)]
        inv["reserved_quantity"] += qty
        reservations.append({"order": oid, "inventory": inv["id"], "quantity": qty})

    # ---- Scenario A: R-104 / P-01 delayed delivery from W-01
    add_order("O-0988", "R-104", "P-01", 36, "delivered", ts(days=-17), ts(days=-14), "W-01")
    add_delivery("O-0988", "delivered", ts(days=-15), ts(days=-14), ts(days=-14, hours=-3))
    add_order("O-1012", "R-104", "P-01", 48, "dispatched", ts(days=-6, hours=-1), ts(days=-3, hours=6), "W-01")
    add_delivery("O-1012", "delayed", ts(days=-4, hours=-4.5), ts(days=-3, hours=6), None,
                 "Carrier reported vehicle breakdown en route (simulated)")
    add_order("O-2105", "R-105", "P-01", 200, "allocated", ts(days=-1), ts(days=1), "W-01")
    add_delivery("O-2105", "scheduled", None, ts(days=1))
    reserve("O-2105", "W-01", "P-01", 200)
    visits.append({"id": "SV-0412", "retailer": "R-104", "visited_at": ts(days=-2, hours=-1),
                   "notes": "Surf Excel 1kg facing empty. Owner says the order was promised for 12 Oct.",
                   "observed": [("P-01", "empty")]})

    # ---- Scenario B: R-108 / P-03 no order in lookback window
    add_order("O-0911", "R-108", "P-03", 40, "delivered", ts(days=-37), ts(days=-34), "W-02")
    add_delivery("O-0911", "delivered", ts(days=-35), ts(days=-34), ts(days=-34, hours=-2))
    reserve_b = ("W-02", "P-03", 100)
    add_order("O-2110", "R-110", "P-03", 100, "allocated", ts(days=-1), ts(days=2), "W-02")
    add_delivery("O-2110", "scheduled", None, ts(days=2))
    reserve("O-2110", *reserve_b)
    visits.append({"id": "SV-0418", "retailer": "R-108", "visited_at": ts(days=-4, hours=-2),
                   "notes": "Atta shelf empty. Retailer asked for refill of 5kg packs.",
                   "observed": [("P-03", "empty")]})

    # ---- Scenario C: R-112 / P-05 pending allocation; W-03 reserved by other orders
    add_order("O-2112", "R-112", "P-05", 60, "pending_allocation", ts(days=-3, hours=-2), ts(days=-1, hours=6))
    for oid, rid, qty in (("O-2113", "R-113", 200), ("O-2115", "R-115", 160), ("O-2119", "R-119", 120)):
        add_order(oid, rid, "P-05", qty, "allocated", ts(days=-5), ts(days=1), "W-03")
        add_delivery(oid, "scheduled", None, ts(days=1))
        reserve(oid, "W-03", "P-05", qty)
    add_order("O-2114", "R-114", "P-05", 70, "allocated", ts(days=-2), ts(days=2), "W-01")
    add_delivery("O-2114", "scheduled", None, ts(days=2))
    reserve("O-2114", "W-01", "P-05", 70)

    # ---- Scenario D: R-117 / P-07 cancelled order with no reason, no route inventory
    add_order("O-2117", "R-117", "P-07", 30, "cancelled", ts(days=-10), ts(days=-7), cancel_reason=None)

    # ---- Scenario E: R-106 / P-06 dispatched, delivery record missing
    add_order("O-2106", "R-106", "P-06", 24, "dispatched", ts(days=-4), ts(days=-1), "W-01")

    # ---- background orders (skip pairs that already have explicit orders)
    explicit_pairs = {(o["retailer"], o["product"]) for o in orders} | SCENARIO_PAIRS
    seq = 3001
    for inv in retailer_inventory:
        pair = (inv["retailer"], inv["product"])
        if pair in explicit_pairs:
            continue
        roll = rng.random()
        rid, pid = pair
        wid = ROUTES[RETAILER_DISTRIBUTOR[rid]][0][0]
        oid = f"O-{seq}"
        if roll < 0.50:  # delivered on time
            ago = rng.randint(4, 18)
            add_order(oid, rid, pid, rng.choice([12, 24, 36, 48]), "delivered", ts(days=-ago), ts(days=-ago + 3), wid)
            add_delivery(oid, "delivered", ts(days=-ago + 1), ts(days=-ago + 3), ts(days=-ago + 3, hours=-rng.randint(1, 8)))
        elif roll < 0.58:  # delivered late (historic delay, already resolved)
            ago = rng.randint(6, 16)
            add_order(oid, rid, pid, rng.choice([12, 24]), "delivered", ts(days=-ago), ts(days=-ago + 3), wid)
            add_delivery(oid, "delivered", ts(days=-ago + 1), ts(days=-ago + 3), ts(days=-ago + 4, hours=5),
                         "Delivered one day late (simulated)")
        elif roll < 0.68:  # in transit, on schedule
            add_order(oid, rid, pid, rng.choice([12, 24]), "dispatched", ts(days=-2), ts(days=1), wid)
            add_delivery(oid, "in_transit", ts(days=-1), ts(days=1))
        elif roll < 0.74 and (wid, pid) not in overrides:  # allocated, holds reservation
            qty = rng.choice([20, 30, 40])
            add_order(oid, rid, pid, qty, "allocated", ts(days=-1), ts(days=2), wid)
            add_delivery(oid, "scheduled", None, ts(days=2))
            reserve(oid, wid, pid, qty)
        else:
            continue
        seq += 1

    # ---- background visits: observe in-stock products only
    vseq = 500
    for r in RETAILERS:
        stocked = [i["product"] for i in retailer_inventory
                   if i["retailer"] == r["id"] and i["quantity"] > 0]
        for _ in range(rng.randint(1, 2)):
            obs = rng.sample(stocked, min(2, len(stocked)))
            visits.append({"id": f"SV-0{vseq}", "retailer": r["id"],
                           "visited_at": ts(days=-rng.randint(1, 12), hours=-rng.randint(0, 6)),
                           "notes": "Routine beat visit (simulated).",
                           "observed": [(pid, "available") for pid in obs]})
            vseq += 1

    for inv in list(warehouse_inventory.values()) + retailer_inventory:
        inv["available_quantity"] = max(inv["quantity"] - inv["reserved_quantity"], 0)

    return {
        "listings": listings,
        "warehouse_inventory": list(warehouse_inventory.values()),
        "retailer_inventory": retailer_inventory,
        "orders": orders,
        "deliveries": deliveries,
        "reservations": reservations,
        "visits": visits,
    }


DATASET = _build_dataset()


def _inv_props(inv: dict) -> dict:
    keys = ("id", "quantity", "reserved_quantity", "available_quantity", "captured_at", "location_type")
    return {k: inv[k] for k in keys}


def reset_graph(client: GraphClient) -> dict:
    """Delete and rebuild the demo graph. Returns node/edge counts."""
    d = DATASET
    client.delete_graph()
    for stmt in INDEX_STATEMENTS:
        client.write(stmt)

    w = client.write
    w("UNWIND $rows AS row CREATE (:Retailer {id: row.id, name: row.name, territory: row.territory, location: row.location})",
      {"rows": RETAILERS})
    w("UNWIND $rows AS row CREATE (:Product {id: row.id, name: row.name, brand: row.brand, category: row.category, pack_size: row.pack_size})",
      {"rows": PRODUCTS})
    w("UNWIND $rows AS row CREATE (:Distributor {id: row.id, name: row.name, territory: row.territory})",
      {"rows": DISTRIBUTORS})
    w("UNWIND $rows AS row CREATE (:Warehouse {id: row.id, name: row.name, territory: row.territory})",
      {"rows": WAREHOUSES})
    w("""UNWIND $rows AS row
         MATCH (r:Retailer {id: row.retailer}), (d:Distributor {id: row.distributor})
         CREATE (r)-[:SERVED_BY]->(d)""",
      {"rows": [{"retailer": k, "distributor": v} for k, v in RETAILER_DISTRIBUTOR.items()]})
    w("""UNWIND $rows AS row
         MATCH (d:Distributor {id: row.d}), (wh:Warehouse {id: row.w})
         CREATE (d)-[:SOURCES_FROM {priority: row.priority}]->(wh)""",
      {"rows": [{"d": dist, "w": wid, "priority": prio} for dist, lst in ROUTES.items() for wid, prio in lst]})
    w("""UNWIND $rows AS row
         MATCH (r:Retailer {id: row.retailer}), (p:Product {id: row.product})
         CREATE (r)-[:LISTS {since: row.since}]->(p)""",
      {"rows": d["listings"]})
    w("""UNWIND $rows AS row
         MATCH (wh:Warehouse {id: row.owner}), (p:Product {id: row.product})
         CREATE (wh)-[:HOLDS]->(i:Inventory)-[:OF_PRODUCT]->(p)
         SET i = row.props""",
      {"rows": [{"owner": i["warehouse"], "product": i["product"], "props": _inv_props(i)} for i in d["warehouse_inventory"]]})
    w("""UNWIND $rows AS row
         MATCH (r:Retailer {id: row.owner}), (p:Product {id: row.product})
         CREATE (r)-[:HOLDS]->(i:Inventory)-[:OF_PRODUCT]->(p)
         SET i = row.props""",
      {"rows": [{"owner": i["retailer"], "product": i["product"], "props": _inv_props(i)} for i in d["retailer_inventory"]]})
    w("""UNWIND $rows AS row
         MATCH (r:Retailer {id: row.retailer}), (p:Product {id: row.product}), (dist:Distributor {id: row.distributor})
         CREATE (o:Order {id: row.id, quantity: row.quantity, status: row.status,
                          ordered_at: row.ordered_at, promised_at: row.promised_at})
         CREATE (o)-[:FOR_RETAILER]->(r), (o)-[:FOR_PRODUCT]->(p), (o)-[:ASSIGNED_TO]->(dist)
         SET o.cancel_reason = row.cancel_reason""",
      {"rows": d["orders"]})
    w("""UNWIND $rows AS row
         MATCH (o:Order {id: row.id}), (wh:Warehouse {id: row.warehouse})
         CREATE (o)-[:ALLOCATED_FROM]->(wh)""",
      {"rows": [o for o in d["orders"] if o["warehouse"]]})
    w("""UNWIND $rows AS row
         MATCH (o:Order {id: row.order}), (i:Inventory {id: row.inventory})
         CREATE (o)-[:RESERVES {quantity: row.quantity}]->(i)""",
      {"rows": d["reservations"]})
    w("""UNWIND $rows AS row
         MATCH (o:Order {id: row.order})
         CREATE (del:Delivery {id: row.id, status: row.status, expected_at: row.expected_at})-[:FULFILLS]->(o)
         SET del.dispatched_at = row.dispatched_at, del.delivered_at = row.delivered_at, del.note = row.note""",
      {"rows": d["deliveries"]})
    w("""UNWIND $rows AS row
         MATCH (r:Retailer {id: row.retailer})
         CREATE (v:SalesVisit {id: row.id, visited_at: row.visited_at, notes: row.notes})-[:AT_RETAILER]->(r)""",
      {"rows": [{k: v[k] for k in ("id", "retailer", "visited_at", "notes")} for v in d["visits"]]})
    w("""UNWIND $rows AS row
         MATCH (v:SalesVisit {id: row.visit}), (p:Product {id: row.product})
         CREATE (v)-[:OBSERVED {shelf_status: row.status}]->(p)""",
      {"rows": [{"visit": v["id"], "product": pid, "status": st} for v in d["visits"] for pid, st in v["observed"]]})
    w("""UNWIND $rows AS row
         MATCH (p:Product {id: row.product})
         CREATE (pr:Promotion {id: row.id, name: row.name, start_date: row.start_date, end_date: row.end_date,
                               status: row.status, territory: row.territory, mechanic: row.mechanic})-[:PROMOTES]->(p)""",
      {"rows": PROMOTIONS})
    return graph_counts(client)


def graph_counts(client: GraphClient) -> dict:
    try:
        nodes = client.read("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY label")
    except GraphMissing:
        return {"nodes": {}, "total_nodes": 0, "total_relationships": 0, "seed_version": None}
    edges = client.read("MATCH ()-[r]->() RETURN count(r)")
    return {
        "nodes": {row[0]: row[1] for row in nodes.rows},
        "total_nodes": sum(row[1] for row in nodes.rows),
        "total_relationships": edges.rows[0][0] if edges.rows else 0,
        "seed_version": SEED_VERSION,
    }


def ensure_seeded(client: GraphClient) -> bool:
    """Seed only if the graph is empty. Returns True if seeding happened."""
    try:
        res = client.read("MATCH (r:Retailer) RETURN count(r)")
        if res.rows and res.rows[0][0] > 0:
            return False
    except GraphMissing:
        pass
    reset_graph(client)
    return True

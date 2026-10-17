"""Evidence engine: turns tool results into facts, inferences, gaps and a probable cause.

This module is pure (no database access). It only reasons over records that the
investigation tools actually returned, so every fact cites record IDs from the graph.

Vocabulary
  * observed fact  - a statement that restates a returned record
  * inference      - a conclusion drawn from one or more facts (cites fact IDs)
  * missing info   - a record or link that was expected but not returned. Absence in
                     the records is NOT treated as proof of real-world absence.
  * contradiction  - two returned records that disagree
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

ACTIVE_ORDER_STATUSES = {"pending", "pending_allocation", "allocated", "dispatched"}
STALE_SNAPSHOT_HOURS = 72

CONFIDENCE_RULES = {
    "high": "A directly linked chain of returned records (order → delivery, or order → reserved "
            "inventory) explains the gap, with the key timestamps present.",
    "medium": "Relevant records exist, but a key link, timestamp or confirmation is missing, or the "
              "explanation rests on a record that was not found.",
    "low": "The returned records are insufficient to distinguish between competing explanations.",
}

STATUS_MEANING = {
    "supported": "Directly supported by linked records",
    "hypothesis": "Plausible explanation that still needs confirmation",
    "record_gap": "Explanation is a gap in the available records",
    "undetermined": "Root cause cannot be determined from available records",
    "not_applicable": "No stockout is recorded",
}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _fmt(value: str | None) -> str:
    d = _dt(value)
    return d.strftime("%d %b %Y %H:%M") if d else "unknown time"


def available(inv: dict | None) -> int | None:
    if inv is None:
        return None
    if inv.get("computed_available") is not None:
        return int(inv["computed_available"])
    return max(int(inv.get("quantity", 0)) - int(inv.get("reserved_quantity", 0)), 0)


@dataclass
class Findings:
    facts: list[dict] = field(default_factory=list)
    inferences: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    relevance: dict[str, str] = field(default_factory=dict)  # record id -> why it matters

    def fact(self, statement: str, records: list[str], tool: str, why: str | None = None) -> str:
        fid = f"F{len(self.facts) + 1}"
        records = [r for r in records if r]
        self.facts.append({"id": fid, "statement": statement, "record_ids": records, "source_tool": tool})
        for r in records:
            if why and r not in self.relevance:
                self.relevance[r] = why
        return fid

    def infer(self, statement: str, based_on: list[str]) -> str:
        iid = f"I{len(self.inferences) + 1}"
        self.inferences.append({"id": iid, "statement": statement, "based_on": [b for b in based_on if b]})
        return iid

    def gap(self, item: str, why: str, check: str) -> None:
        self.missing.append({"item": item, "why_it_matters": why, "suggested_check": check})

    def action(self, action: str, owner: str, priority: str, rationale: str) -> None:
        self.actions.append({"action": action, "owner": owner, "priority": priority, "rationale": rationale})


def analyse(ev: dict) -> dict:
    """Main entry. `ev` is the bundle assembled by the investigation service."""
    f = Findings()
    now = _dt(ev["now"])
    retailer, product = ev["retailer"], ev["product"]
    rid, pid = retailer["id"], product["id"]
    pname = product["name"]

    # ------------------------------------------------------------ retailer stock
    stock = ev["retailer_stock"][0] if ev["retailer_stock"] else None
    stock_fact = None
    if not ev.get("listed"):
        f.gap(f"No LISTS relationship between {rid} and {pid}",
              "The product may not be part of this retailer's agreed assortment.",
              "Confirm the assortment/listing with the distributor or key-account team.")
    if stock is None:
        f.gap(f"No stock snapshot for {pid} at {rid}",
              "Without a retailer stock record a stockout cannot be confirmed from data.",
              "Request a physical shelf and back-room count at the retailer.")
    else:
        stock_avail = available(stock)
        stock_fact = f.fact(
            f"Retailer stock record {stock['id']} (captured {_fmt(stock.get('captured_at'))}) shows "
            f"{stock['quantity']} physical, {stock.get('reserved_quantity', 0)} reserved, {stock_avail} available units of {pname}.",
            [stock["id"]], "get_retailer_stock", "Retailer's own stock position for the product")
        if stock.get("available_quantity") is not None and int(stock["available_quantity"]) != stock_avail:
            f.contradictions.append({
                "statement": f"{stock['id']} stores available_quantity={stock['available_quantity']} but quantity − reserved = {stock_avail}.",
                "record_ids": [stock["id"]]})
        cap = _dt(stock.get("captured_at"))
        if cap and now and (now - cap).total_seconds() / 3600 > STALE_SNAPSHOT_HOURS:
            f.gap(f"Fresh stock count for {stock['id']}",
                  f"The snapshot is {int((now - cap).total_seconds() // 86400)} days old; current shelf stock may differ.",
                  "Ask the sales representative to recount the product at the retailer.")

    # ------------------------------------------------------------ supply network
    network = ev["network"]
    distributors = {n["distributor"]["id"]: n["distributor"] for n in network if n.get("distributor")}
    route_facts: dict[str, str] = {}
    route_with_records = [n for n in network if n.get("inventory")]
    if not network:
        f.gap(f"No SERVED_BY → SOURCES_FROM route for {rid}",
              "Without a recorded distributor and warehouse route, replenishment cannot be traced.",
              "Confirm which distributor services this retailer and which warehouses they draw from.")
    for n in network:
        d, w, inv = n["distributor"], n["warehouse"], n.get("inventory")
        if inv is None:
            route_facts[w["id"]] = f.fact(
                f"Route {d['id']} {d['name']} → {w['id']} {w['name']} (priority {n['priority']}) exists, "
                f"but no inventory record for {pid} was returned at {w['id']}.",
                [d["id"], w["id"]], "trace_supply_network", "Replenishment route without a stock record")
            f.gap(f"Inventory record for {pid} at {w['id']} {w['name']}",
                  "Network availability on this route is unknown, so supply shortage cannot be confirmed or ruled out.",
                  f"Request a current stock count for {pid} at {w['name']}.")
        else:
            a = available(inv)
            route_facts[w["id"]] = f.fact(
                f"Route {d['id']} {d['name']} → {w['id']} {w['name']} (priority {n['priority']}): inventory {inv['id']} "
                f"shows {inv['quantity']} physical − {inv['reserved_quantity']} reserved = {a} available.",
                [d["id"], w["id"], inv["id"]], "trace_supply_network",
                "Stock on a warehouse that can replenish this retailer")
            if inv.get("available_quantity") is not None and int(inv["available_quantity"]) != a:
                f.contradictions.append({
                    "statement": f"{inv['id']} stores available_quantity={inv['available_quantity']} but quantity − reserved = {a}.",
                    "record_ids": [inv["id"]]})

    off_route_facts = []
    for o in ev.get("off_route", []):
        off_route_facts.append(f.fact(
            f"{o['warehouse']['id']} {o['warehouse']['name']} holds {available(o['inventory'])} available units "
            f"({o['inventory']['id']}), but no recorded route connects {rid}'s distributor to it.",
            [o["warehouse"]["id"], o["inventory"]["id"]], "find_off_route_stock",
            "Stock exists in the network but is not on this retailer's recorded route"))

    # reservations
    res_by_inv: dict[str, list[dict]] = {}
    for r in ev.get("reservations", []):
        res_by_inv.setdefault(r["inventory_id"], []).append(r)
    reservation_facts: dict[str, str] = {}
    for inv_id, rs in res_by_inv.items():
        parts = ", ".join(f"{r['order']['id']} ({r['retailer']['id'] if r.get('retailer') else '?'}, {r['quantity']})" for r in rs)
        reservation_facts[inv_id] = f.fact(
            f"Reservations returned on {inv_id}: {parts}; total {sum(r['quantity'] for r in rs)} units.",
            [inv_id] + [r["order"]["id"] for r in rs], "inspect_reservations",
            "Order holding reserved stock on a route warehouse")
    for n in route_with_records:
        inv = n["inventory"]
        total = sum(r["quantity"] for r in res_by_inv.get(inv["id"], []))
        if int(inv["reserved_quantity"]) != total:
            f.contradictions.append({
                "statement": f"{inv['id']} records reserved_quantity={inv['reserved_quantity']}, but returned RESERVES "
                             f"links total {total}.",
                "record_ids": [inv["id"]]})

    # ------------------------------------------------------------ orders & deliveries
    recent = ev["orders"]["recent"]
    prior = ev["orders"].get("prior")
    order_facts: dict[str, str] = {}
    delivery_facts: dict[str, str] = {}
    for o in recent:
        od = o["order"]
        wtxt = f", allocated from {o['warehouse']['id']}" if o.get("warehouse") else ", not allocated to a warehouse"
        dtxt = f" assigned to {o['distributor']['id']}" if o.get("distributor") else ""
        order_facts[od["id"]] = f.fact(
            f"Order {od['id']}: {od['quantity']} units, status '{od['status']}', ordered {_fmt(od.get('ordered_at'))}, "
            f"promised {_fmt(od.get('promised_at'))},{dtxt}{wtxt}.",
            [od["id"]] + ([o["distributor"]["id"]] if o.get("distributor") else []) + ([o["warehouse"]["id"]] if o.get("warehouse") else []),
            "trace_order_fulfillment", "Replenishment order for this retailer and product")
        dl = o.get("delivery")
        if dl:
            delivered = f"delivered {_fmt(dl['delivered_at'])}" if dl.get("delivered_at") else "no delivered_at recorded"
            note = f" Note: {dl['note']}" if dl.get("note") else ""
            delivery_facts[od["id"]] = f.fact(
                f"Delivery {dl['id']} for {od['id']}: status '{dl['status']}', expected {_fmt(dl.get('expected_at'))}, {delivered}.{note}",
                [dl["id"], od["id"]], "trace_order_fulfillment", "Shipment linked to the replenishment order")
            if dl.get("status") == "delivered" and od.get("status") != "delivered":
                f.contradictions.append({"statement": f"{dl['id']} is delivered but {od['id']} status is '{od['status']}'.",
                                         "record_ids": [dl["id"], od["id"]]})
            if od.get("status") == "delivered" and dl.get("status") != "delivered":
                f.contradictions.append({"statement": f"{od['id']} is delivered but {dl['id']} status is '{dl['status']}'.",
                                         "record_ids": [dl["id"], od["id"]]})
    no_order_fact = None
    if not recent:
        no_order_fact = f.fact(
            f"No order for {pid} to {rid} was returned for the lookback window starting {_fmt(ev['since'])}.",
            [], "trace_order_fulfillment")
        if prior:
            po = prior["order"]
            f.fact(f"The most recent earlier order is {po['id']} ({po['status']}, ordered {_fmt(po.get('ordered_at'))}).",
                   [po["id"]], "last_order_before_window", "Last replenishment before the lookback window")

    # ------------------------------------------------------------ visits & promotions
    visit_facts = []
    observed_visits = [v for v in ev.get("visits", []) if v["observed_product"]]
    for v in observed_visits:
        vd = v["visit"]
        visit_facts.append(f.fact(
            f"Sales visit {vd['id']} on {_fmt(vd.get('visited_at'))} recorded shelf status '{v['shelf_status']}' "
            f"for {pid}. Notes: “{vd.get('notes', '')}”",
            [vd["id"]], "inspect_sales_visits", "Field observation of the shelf"))
        if stock and v["shelf_status"] == "available" and available(stock) == 0:
            vt, st = _dt(vd.get("visited_at")), _dt(stock.get("captured_at"))
            if vt and st and vt > st:
                f.contradictions.append({
                    "statement": f"{vd['id']} saw the product on shelf after {stock['id']} recorded zero stock.",
                    "record_ids": [vd["id"], stock["id"]]})
    if not observed_visits:
        f.gap(f"Recent sales-visit observation of {pid} at {rid}",
              "A field observation would confirm the shelf position independently of system stock.",
              "Ask the territory sales representative to check the shelf on the next beat visit.")
    promo_facts = []
    for pr in ev.get("promotions", []):
        promo_facts.append(f.fact(
            f"Promotion {pr['id']} '{pr['name']}' ({pr.get('mechanic', '')}) is active {pr['start_date']} to {pr['end_date']} "
            f"in {pr['territory']}.", [pr["id"]], "inspect_active_promotions", "Promotion that can raise demand"))

    # ------------------------------------------------------------ decide probable cause
    ctx = dict(f=f, ev=ev, now=now, stock=stock, stock_fact=stock_fact, network=network,
               route_facts=route_facts, off_route_facts=off_route_facts, reservation_facts=reservation_facts,
               order_facts=order_facts, delivery_facts=delivery_facts, recent=recent,
               no_order_fact=no_order_fact, visit_facts=visit_facts, promo_facts=promo_facts,
               distributors=distributors, res_by_inv=res_by_inv)
    cause = _decide(ctx)
    path = cause.get("path", [])
    for must in (rid, pid, stock["id"] if stock else None):
        if must and must not in path:
            path.append(must)
    cause["path"] = path

    if promo_facts and cause["code"] not in ("NO_STOCKOUT",):
        f.infer("An active promotion may have increased demand for the product; this is context, "
                "not evidence of the fulfilment failure itself.", promo_facts)
    if f.contradictions:
        cause.setdefault("weaken", []).append("Resolving the contradictory records listed below.")

    return {
        "probable_cause": {
            "code": cause["code"], "label": cause["label"], "status": cause["status"],
            "status_meaning": STATUS_MEANING[cause["status"]],
            "confidence": cause["confidence"], "confidence_basis": CONFIDENCE_RULES[cause["confidence"]],
        },
        "summary": cause["summary"],
        "observed_facts": f.facts,
        "inferences": f.inferences,
        "missing_information": f.missing,
        "contradictions": f.contradictions,
        "recommended_actions": f.actions,
        "hypothesis_tests": {"would_strengthen": cause.get("strengthen", []), "would_weaken": cause.get("weaken", [])},
        "path_ids": [p for p in cause.get("path", []) if p],
        "relevance": f.relevance,
    }


def _route_entries(network: list[dict]) -> list[dict]:
    return sorted([n for n in network if n.get("warehouse")], key=lambda n: (n.get("priority") or 99))


def _decide(c: dict) -> dict:
    f: Findings = c["f"]
    ev, now, stock = c["ev"], c["now"], c["stock"]
    rid, pid = ev["retailer"]["id"], ev["product"]["id"]
    rname, pname = ev["retailer"]["name"], ev["product"]["name"]
    routes = _route_entries(c["network"])
    primary = routes[0] if routes else None
    base_path = [rid] + ([primary["distributor"]["id"], primary["warehouse"]["id"]] if primary else [])
    if primary and primary.get("inventory"):
        base_path += [primary["inventory"]["id"], pid]
    route_avail = sum(available(n["inventory"]) or 0 for n in routes if n.get("inventory"))
    route_physical = sum(int(n["inventory"]["quantity"]) for n in routes if n.get("inventory"))
    dist_name = primary["distributor"]["name"] if primary else "the distributor"
    dist_id = primary["distributor"]["id"] if primary else None

    # 0. no stockout recorded
    if stock is not None and (available(stock) or 0) > 0:
        f.action("No replenishment action required; monitor sell-through.", "Territory sales manager", "low",
                 "The retailer stock record shows available units.")
        return {"code": "NO_STOCKOUT", "label": "No stockout recorded", "status": "not_applicable",
                "confidence": "high",
                "summary": f"{rname} has {available(stock)} available units of {pname} according to {stock['id']} "
                           f"(captured {_fmt(stock.get('captured_at'))}). No stockout is recorded.",
                "path": [rid, stock["id"], pid],
                "strengthen": ["A recent sales-visit observation confirming product on shelf."],
                "weaken": ["A newer stock count showing zero units."]}

    stock_note = f"{stock['id']} shows 0 available" if stock else "no retailer stock record was returned"
    active = [o for o in c["recent"] if o["order"].get("status") in ACTIVE_ORDER_STATUSES]
    active.sort(key=lambda o: o["order"].get("ordered_at") or "", reverse=True)

    # 1. active order exists
    if active:
        o = active[0]
        od, dl = o["order"], o.get("delivery")
        ofact = c["order_facts"].get(od["id"])
        dfact = c["delivery_facts"].get(od["id"])
        wh = o.get("warehouse") or (primary["warehouse"] if primary else None)
        path = base_path + [od["id"]] + ([dl["id"]] if dl else [])
        if o.get("warehouse") and o["warehouse"]["id"] not in path:
            path.append(o["warehouse"]["id"])

        if dl:
            expected = _dt(dl.get("expected_at"))
            overdue = expected is not None and now is not None and expected < now and not dl.get("delivered_at")
            if dl.get("status") == "delayed" or (dl.get("status") in ("dispatched", "in_transit") and overdue):
                hours = int((now - expected).total_seconds() // 3600) if overdue else None
                late = f"{hours} hours past its expected time" if hours else "marked delayed"
                i1 = f.infer(f"The replenishment for {rid} is in the delivery leg: {od['id']} was dispatched, "
                             f"but {dl['id']} is {late}.", [ofact, dfact])
                if primary and primary.get("inventory") and route_avail > 0:
                    f.infer(f"Warehouse stock is not the constraint: the route still shows {route_avail} available units.",
                            [c["route_facts"].get(primary["warehouse"]["id"])])
                f.infer(f"Shelf stock at {rid} cannot recover until {dl['id']} arrives or a replacement shipment is sent.",
                        [i1, c["stock_fact"]])
                conf = "high" if expected is not None and ofact and dfact else "medium"
                f.action(f"Ask {dist_name} ({dist_id}) to investigate the delayed shipment {dl['id']} and confirm a revised ETA.",
                         f"{dist_name} logistics", "high", f"{dl['id']} is the open fulfilment record for {od['id']}.")
                if route_avail >= int(od["quantity"]):
                    f.action(f"If the ETA is not credible, raise an emergency replenishment of {od['quantity']} units from "
                             f"{wh['name'] if wh else 'the route warehouse'}.", "Distribution manager", "medium",
                             f"Route warehouse has {route_avail} available units.")
                f.action(f"Inform {rname} of the expected arrival.", "Territory sales representative", "low",
                         "Retailer was promised delivery by " + _fmt(od.get("promised_at")))
                return {"code": "DELAYED_DELIVERY", "label": "Delayed replenishment delivery", "status": "supported",
                        "confidence": conf,
                        "summary": f"{pname} is unavailable at {rname} because the linked replenishment shipment {dl['id']} "
                                   f"for order {od['id']} is delayed ({late}), while {stock_note}. "
                                   f"Warehouse stock exists on the route ({route_avail} available), so the gap is in delivery, not supply.",
                        "path": path,
                        "strengthen": [f"Carrier/GPS confirmation that {dl['id']} is still undelivered.",
                                       f"Distributor confirmation of the delay reason for {dl['id']}."],
                        "weaken": [f"A proof-of-delivery for {dl['id']} (then check why stock was not booked in).",
                                   "A retailer stock count showing units on hand."]}
            if dl.get("status") == "failed":
                f.infer(f"{dl['id']} failed, so {od['id']} has not replenished the retailer.", [ofact, dfact])
                f.action(f"Ask {dist_name} to re-dispatch {od['id']} and record the failure reason.",
                         f"{dist_name} logistics", "high", f"{dl['id']} status is failed.")
                return {"code": "FAILED_DELIVERY", "label": "Failed delivery", "status": "supported", "confidence": "high",
                        "summary": f"The shipment {dl['id']} for {od['id']} failed, so {rname} has not been replenished with {pname}.",
                        "path": path, "strengthen": [f"Failure reason recorded on {dl['id']}."],
                        "weaken": ["A later successful delivery for the same order."]}
            if dl.get("status") in ("scheduled", "dispatched", "in_transit"):
                f.infer(f"A replenishment is on its way and not yet overdue: {dl['id']} is expected {_fmt(dl.get('expected_at'))}.",
                        [ofact, dfact])
                f.action(f"Confirm {dl['id']} arrives by {_fmt(dl.get('expected_at'))}; escalate if it slips.",
                         f"{dist_name} logistics", "medium", "Delivery is in progress.")
                return {"code": "REPLENISHMENT_IN_PROGRESS", "label": "Replenishment in progress (on schedule)",
                        "status": "supported", "confidence": "medium",
                        "summary": f"{rname} is out of {pname} ({stock_note}), but order {od['id']} is linked to delivery "
                                   f"{dl['id']} ('{dl['status']}'), expected {_fmt(dl.get('expected_at'))}. The stockout should "
                                   f"clear on arrival.",
                        "path": path, "strengthen": ["Carrier confirmation of the ETA."],
                        "weaken": [f"{dl['id']} passing its expected time without a delivery record."]}

        # active order without a delivery record
        if od.get("status") == "dispatched":
            f.infer(f"{od['id']} is marked dispatched, but no linked delivery record was returned, so its "
                    f"whereabouts cannot be traced from the graph.", [ofact])
            f.gap(f"Delivery record linked to {od['id']}",
                  "A dispatched order should have a delivery (FULFILLS) record with status and ETA.",
                  f"Ask {dist_name} for the shipment/LR number and ETA for {od['id']}.")
            f.action(f"Request the shipment details for {od['id']} from {dist_name} and create the missing delivery record.",
                     f"{dist_name} logistics", "high", "Dispatched order has no traceable delivery.")
            return {"code": "MISSING_DELIVERY_RECORD", "label": "Dispatched order has no delivery record",
                    "status": "record_gap", "confidence": "medium",
                    "summary": f"Order {od['id']} for {pname} at {rname} is marked dispatched, but no delivery record is "
                               f"linked to it, while {stock_note}. The shipment may be in transit, lost, or simply unrecorded; "
                               f"the records cannot tell which.",
                    "path": path,
                    "strengthen": [f"Distributor confirms no vehicle was assigned to {od['id']}."],
                    "weaken": [f"A delivery record for {od['id']} with a recent proof-of-delivery."]}

        # pending / allocated without a delivery -> check available stock on route
        qty = int(od["quantity"])
        route_inv = [n for n in routes if n.get("inventory")]
        prim_inv = route_inv[0]["inventory"] if route_inv else None
        if prim_inv is not None and available(prim_inv) < qty <= int(prim_inv["quantity"]):
            pw = route_inv[0]["warehouse"]
            res_fact = c["reservation_facts"].get(prim_inv["id"])
            i1 = f.infer(f"{pw['id']} has {prim_inv['quantity']} physical units, but after {prim_inv['reserved_quantity']} "
                         f"reserved only {available(prim_inv)} are available, which is less than the {qty} units {od['id']} needs.",
                         [c["route_facts"].get(pw["id"]), res_fact, ofact])
            f.infer(f"{od['id']} remains '{od['status']}' because allocatable stock, not physical stock, is short.", [i1])
            alts = [n for n in route_inv[1:] if (available(n["inventory"]) or 0) >= qty]
            path = [rid, route_inv[0]["distributor"]["id"], pw["id"], prim_inv["id"], pid, od["id"]]
            if res_fact:
                path += [r["order"]["id"] for r in c["res_by_inv"].get(prim_inv["id"], [])]
            f.action(f"Review reservations on {prim_inv['id']} - check whether any can be released, split or re-prioritised.",
                     "Supply planner", "high", f"{prim_inv['reserved_quantity']} of {prim_inv['quantity']} units are reserved.")
            for alt in alts:
                f.action(f"Allocate {od['id']} from alternative route warehouse {alt['warehouse']['id']} {alt['warehouse']['name']} "
                         f"(priority {alt['priority']}, {available(alt['inventory'])} available).",
                         f"{alt['distributor']['name']}", "high", "Alternative fulfilment on a recorded route.")
                path += [alt["warehouse"]["id"], alt["inventory"]["id"]]
                f.infer(f"{alt['warehouse']['id']} is a recorded secondary source for {alt['distributor']['id']} with enough "
                        f"available stock to fulfil {od['id']}.", [c["route_facts"].get(alt["warehouse"]["id"])])
            if not alts:
                f.action("No recorded alternative route has enough stock; consider an inter-warehouse transfer.",
                         "Supply planner", "medium", "Off-route stock may exist (see evidence).")
            return {"code": "RESERVED_STOCK", "label": "Stock is physically present but reserved",
                    "status": "supported", "confidence": "high" if res_fact else "medium",
                    "summary": f"{pw['name']} physically holds {prim_inv['quantity']} units of {pname}, but "
                               f"{prim_inv['reserved_quantity']} are reserved by other orders, leaving {available(prim_inv)} "
                               f"available - less than the {qty} units in {rname}'s order {od['id']}, which is still "
                               f"'{od['status']}'." + (f" A secondary route warehouse can cover it." if alts else ""),
                    "path": path,
                    "strengthen": ["Allocation log showing the order was rejected for insufficient available stock."],
                    "weaken": ["Reservations that have already been released but not updated in the record."]}
        if prim_inv is not None and int(prim_inv["quantity"]) < qty:
            f.infer(f"Route stock ({prim_inv['quantity']} physical) cannot cover {od['id']} ({qty} units).",
                    [c["route_facts"].get(routes[0]["warehouse"]["id"]), ofact])
            f.action("Raise a stock transfer or purchase for the route warehouse.", "Supply planner", "high",
                     "Physical stock shortage on the route.")
            return {"code": "INSUFFICIENT_NETWORK_STOCK", "label": "Insufficient physical stock on route",
                    "status": "supported", "confidence": "high",
                    "summary": f"Order {od['id']} cannot be fulfilled because the route warehouse holds only "
                               f"{prim_inv['quantity']} physical units of {pname}.",
                    "path": base_path + [od["id"]], "strengthen": [], "weaken": ["A pending inbound receipt at the warehouse."]}
        f.infer(f"{od['id']} is '{od['status']}' with no delivery yet, while route stock appears sufficient.", [ofact])
        f.action(f"Ask {dist_name} why {od['id']} has not been dispatched.", f"{dist_name}", "medium",
                 "Order is open and stock appears available.")
        return {"code": "ORDER_AWAITING_DISPATCH", "label": "Order awaiting dispatch", "status": "hypothesis",
                "confidence": "medium",
                "summary": f"Order {od['id']} for {pname} at {rname} is '{od['status']}' and has no delivery yet, although "
                           f"route stock appears sufficient ({route_avail} available).",
                "path": base_path + [od["id"]],
                "strengthen": ["Distributor confirms a dispatch backlog."], "weaken": ["A delivery record created for the order."]}

    # 2. recently delivered order but still zero
    delivered = [o for o in c["recent"] if o["order"].get("status") == "delivered" and o.get("delivery")]
    delivered.sort(key=lambda o: o["delivery"].get("delivered_at") or "", reverse=True)
    if delivered and stock is not None:
        o = delivered[0]
        od, dl = o["order"], o["delivery"]
        dat, cap = _dt(dl.get("delivered_at")), _dt(stock.get("captured_at"))
        ofact, dfact = c["order_facts"].get(od["id"]), c["delivery_facts"].get(od["id"])
        path = base_path + [od["id"], dl["id"], stock["id"]]
        if dat and cap and dat > cap:
            f.infer(f"{dl['id']} was recorded as delivered at {_fmt(dl['delivered_at'])}, after the latest stock snapshot "
                    f"{stock['id']} ({_fmt(stock['captured_at'])}). The zero-stock record may simply predate the delivery.",
                    [dfact, c["stock_fact"]])
            f.gap(f"Goods receipt / stock update after {dl['id']}",
                  "A delivered shipment does not automatically update retailer stock in the records.",
                  f"Recount {pid} at {rid} or confirm the goods receipt for {od['id']}.")
            f.action(f"Recount {pname} at {rname} and update {stock['id']}.", "Territory sales representative", "high",
                     "Stock record predates the delivery.")
            f.action(f"Confirm proof-of-delivery and quantity received for {dl['id']}.", f"{dist_name} logistics", "medium",
                     "Verifies the shipment actually reached the shelf.")
            return {"code": "DELIVERY_NOT_REFLECTED", "label": "Delivered stock not yet reflected in retailer inventory",
                    "status": "hypothesis", "confidence": "medium",
                    "summary": f"Delivery {dl['id']} for order {od['id']} is now recorded as delivered "
                               f"({_fmt(dl['delivered_at'])}), but the retailer stock record {stock['id']} still shows zero and was "
                               f"captured earlier ({_fmt(stock['captured_at'])}). The delay explanation no longer applies; the "
                               f"open question is whether the delivered quantity has been booked into stock.",
                    "path": path,
                    "strengthen": [f"A goods-receipt record for {dl['id']} without a matching stock update."],
                    "weaken": [f"A recount at {rid} that still shows zero (would point to depletion or short delivery)."]}
        f.infer(f"{dl['id']} was delivered before the latest zero-stock snapshot, so the delivered units appear to have "
                f"been sold through or not received in full.", [dfact, c["stock_fact"]] + c["promo_facts"])
        f.action(f"Raise a new replenishment order for {pname} at {rname}.", f"{dist_name}", "high",
                 "No open order exists and the shelf is empty.")
        f.action(f"Confirm the quantity actually received on {dl['id']}.", f"{dist_name} logistics", "medium",
                 "Distinguishes sell-through from short delivery.")
        return {"code": "DEPLETED_AFTER_DELIVERY", "label": "Stock depleted after last delivery", "status": "hypothesis",
                "confidence": "medium" if c["promo_facts"] else "low",
                "summary": f"The last order {od['id']} was delivered ({_fmt(dl.get('delivered_at'))}) before the latest stock "
                           f"count, which still shows zero. No open replenishment order exists, so the shelf will stay empty "
                           f"until a new order is placed.",
                "path": path, "strengthen": ["Sell-through data showing high recent sales."],
                "weaken": [f"Proof that {dl['id']} delivered fewer units than ordered."]}

    route_known = any(n.get("inventory") for n in routes)
    cancelled = [o for o in c["recent"] if o["order"].get("status") == "cancelled"]

    # 3. no usable route inventory -> cannot determine
    if not route_known:
        for o in cancelled:
            od = o["order"]
            if not od.get("cancel_reason"):
                f.gap(f"Cancellation reason for {od['id']}",
                      "The order was cancelled without a recorded reason; it may or may not be related to supply.",
                      f"Ask {dist_name} why {od['id']} was cancelled.")
        alt_note = ""
        if c["off_route_facts"]:
            f.infer("Stock exists elsewhere in the network, but the records show no route connecting it to this retailer, "
                    "so it cannot be assumed to be obtainable.", c["off_route_facts"])
            alt_note = " Stock exists in an off-route warehouse, but no recorded route connects it to this retailer."
        f.action(f"Obtain a current stock count for {pid} at the route warehouse(s) "
                 f"{', '.join(n['warehouse']['id'] for n in routes) or '(none recorded)'}.",
                 "Supply planner", "high", "Route inventory is unknown.")
        if cancelled:
            f.action(f"Confirm why order {cancelled[0]['order']['id']} was cancelled.", f"{dist_name}", "high",
                     "Cancelled order has no reason.")
        f.action(f"Verify the shelf position of {pname} at {rname} with a fresh count.", "Territory sales representative",
                 "medium", "Retailer snapshot may be stale.")
        path = base_path + [o["order"]["id"] for o in cancelled]
        return {"code": "UNDETERMINED", "label": "Root cause cannot be determined", "status": "undetermined",
                "confidence": "low",
                "summary": f"The available records do not explain why {pname} is unavailable at {rname}: {stock_note}, "
                           f"no inventory record for the product was returned on the retailer's supply route"
                           + (f", and the most recent order {cancelled[0]['order']['id']} was cancelled without a reason" if cancelled else "")
                           + f".{alt_note} See the missing evidence below.",
                "path": path,
                "strengthen": ["A route warehouse stock count of zero (would indicate supply shortage).",
                               "A recorded cancellation reason citing no stock."],
                "weaken": ["A route warehouse count showing ample stock (would point to an ordering gap)."]}

    # 4. cancelled order, route stock known
    if cancelled:
        od = cancelled[0]["order"]
        reason = od.get("cancel_reason")
        f.infer(f"The last replenishment attempt {od['id']} was cancelled"
                f"{' (' + reason + ')' if reason else ' without a recorded reason'} and no replacement order was returned.",
                [c["order_facts"].get(od["id"])])
        if not reason:
            f.gap(f"Cancellation reason for {od['id']}", "Needed to know whether to re-order or fix a supply issue.",
                  f"Ask {dist_name}.")
        f.action(f"Verify the replenishment requirement and raise a replacement for {od['id']}.", f"{dist_name}", "high",
                 f"Route stock available: {route_avail}.")
        return {"code": "CANCELLED_ORDER", "label": "Replenishment order cancelled", "status": "hypothesis",
                "confidence": "medium",
                "summary": f"The most recent order {od['id']} for {pname} at {rname} was cancelled and no replacement order "
                           f"was found, although route stock is available ({route_avail}).",
                "path": base_path + [od["id"]], "strengthen": ["Cancellation reason recorded."],
                "weaken": ["A replacement order outside the lookback window."]}

    # 5. no order at all in window
    if route_avail <= 0 and route_physical > 0:
        f.infer("Route stock is fully reserved, so even a new order could not be allocated immediately.",
                list(c["route_facts"].values()))
        f.action("Review reservations or source from an alternative warehouse.", "Supply planner", "high",
                 "No available stock on route.")
        return {"code": "RESERVED_STOCK", "label": "Route stock fully reserved", "status": "supported",
                "confidence": "medium",
                "summary": f"No order exists for {pname} at {rname}, and route stock is fully reserved by other orders.",
                "path": base_path, "strengthen": [], "weaken": []}
    f.infer(f"Stock is available on the retailer's route ({route_avail} units), but no replenishment order links it to {rid}. "
            f"The gap is in the ordering records, not in supply.",
            [c["no_order_fact"], c["stock_fact"]] + list(c["route_facts"].values()))
    if c["visit_facts"]:
        f.infer("A field visit already recorded the empty shelf, yet no order followed in the records.", c["visit_facts"])
    f.gap(f"Replenishment order for {pid} to {rid}",
          "No order was returned in the lookback window. This is a gap in the records, not proof that nobody ordered.",
          "Check the distributor's order book and any offline/WhatsApp orders before creating a new one.")
    f.action(f"Verify the replenishment requirement with {rname} and create (or locate) an order for {pname}.",
             f"{dist_name} / territory sales representative", "high",
             f"{route_avail} units are available on route {dist_id}.")
    return {"code": "NO_REPLENISHMENT_ORDER", "label": "No replenishment order on record", "status": "record_gap",
            "confidence": "medium",
            "summary": f"{pname} is unavailable at {rname} ({stock_note}). The supply route has {route_avail} available "
                       f"units, but no replenishment order for this retailer and product was found in the last "
                       f"{ev.get('lookback_days', 21)} days. The records show a missing order; they do not show who should have placed it.",
            "path": base_path,
            "strengthen": ["Distributor confirms no order was received (including offline channels)."],
            "weaken": ["An order found outside the system or outside the lookback window."]}

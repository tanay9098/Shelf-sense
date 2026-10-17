"""Investigation orchestration: question → entities → approved tools → evidence → response."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from app.config import Settings, get_settings
from app.db.connection import GraphClient
from app.db.seed import SCENARIOS
from app.services import evidence_service
from app.services.llm_service import get_summariser
from app.tools import investigation_tools as tools

STOCKOUT_WORDS = re.compile(
    r"\b(why|unavailable|out of stock|stock ?out|missing|empty|no stock|can'?t|cannot|not available|short|shortage|have no|has no)\b",
    re.I)
STOPWORDS = {"the", "and", "store", "stores", "mart", "kirana", "general", "super", "daily", "with", "for",
             "pack", "kg", "ml", "100g", "500g", "120g", "150g", "200ml", "52g"}


class InvestigationError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in STOPWORDS}


def list_retailers(client: GraphClient) -> list[dict]:
    rows = client.read("""MATCH (r:Retailer) OPTIONAL MATCH (r)-[:SERVED_BY]->(d:Distributor)
                          RETURN r.id, r.name, r.territory, r.location, d.id ORDER BY r.id LIMIT 200""").rows
    return [{"id": r[0], "name": r[1], "territory": r[2], "location": r[3], "distributor_id": r[4]} for r in rows]


def list_products(client: GraphClient) -> list[dict]:
    rows = client.read("""MATCH (p:Product) RETURN p.id, p.name, p.brand, p.category, p.pack_size
                          ORDER BY p.id LIMIT 200""").rows
    return [{"id": r[0], "name": r[1], "brand": r[2], "category": r[3], "pack_size": r[4]} for r in rows]


def _best_match(question: str, items: list[dict], fields: tuple[str, ...]) -> list[dict]:
    q = _tokens(question)
    scored = []
    for it in items:
        toks = set().union(*[_tokens(str(it.get(f) or "")) for f in fields])
        score = len(q & toks)
        if score:
            scored.append((score, it))
    if not scored:
        return []
    top = max(s for s, _ in scored)
    return [it for s, it in scored if s == top]


def resolve_question(client: GraphClient, question: str) -> tuple[str | None, str | None, str]:
    """Deterministic entity extraction: explicit IDs first, then name matching."""
    rid = re.search(r"\bR-\d{3}\b", question, re.I)
    pid = re.search(r"\bP-\d{2}\b", question, re.I)
    retailer_id = rid.group(0).upper() if rid else None
    product_id = pid.group(0).upper() if pid else None
    how = []
    if retailer_id:
        how.append("retailer ID in question")
    else:
        cands = _best_match(question, list_retailers(client), ("name", "location"))
        if len(cands) == 1:
            retailer_id = cands[0]["id"]
            how.append("retailer name match")
        elif len(cands) > 1:
            raise InvestigationError("AMBIGUOUS_RETAILER", "The question matches several retailers. Please choose one.",
                                     422, {"candidates": [c["id"] for c in cands[:6]]})
    if product_id:
        how.append("product ID in question")
    else:
        cands = _best_match(question, list_products(client), ("name", "brand"))
        if len(cands) == 1:
            product_id = cands[0]["id"]
            how.append("product name match")
        elif len(cands) > 1 and retailer_id:
            # Disambiguate through the graph: prefer candidates the retailer lists and holds at zero.
            ids = [c["id"] for c in cands]
            rows = client.read("""MATCH (r:Retailer {id: $rid})-[:HOLDS]->(i:Inventory)-[:OF_PRODUCT]->(p:Product)
                                  WHERE p.id IN $ids AND i.quantity - i.reserved_quantity <= 0
                                  RETURN p.id LIMIT 10""", {"rid": retailer_id, "ids": ids}).rows
            zero = [r[0] for r in rows]
            if len(zero) == 1:
                product_id = zero[0]
                how.append("product disambiguated via retailer zero-stock record")
            else:
                raise InvestigationError("AMBIGUOUS_PRODUCT", "The question matches several products. Please choose one.",
                                         422, {"candidates": ids})
        elif len(cands) > 1:
            raise InvestigationError("AMBIGUOUS_PRODUCT", "The question matches several products. Please choose one.",
                                     422, {"candidates": [c["id"] for c in cands[:6]]})
    return retailer_id, product_id, ", ".join(how) or "unresolved"


class InvestigationService:
    def __init__(self, client: GraphClient, settings: Settings | None = None):
        self.client = client
        self.settings = settings or get_settings()

    def investigate(self, question: str | None = None, retailer_id: str | None = None,
                    product_id: str | None = None, scenario_id: str | None = None) -> dict:
        resolved_by = "explicit IDs"
        if scenario_id:
            sc = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
            if sc is None:
                raise InvestigationError("UNKNOWN_SCENARIO", f"Scenario '{scenario_id}' does not exist.", 404)
            retailer_id, product_id = sc["retailer_id"], sc["product_id"]
            question = question or sc["question"]
            resolved_by = f"scenario {scenario_id}"
        elif question and not (retailer_id and product_id):
            q_r, q_p, how = resolve_question(self.client, question)
            retailer_id, product_id = retailer_id or q_r, product_id or q_p
            resolved_by = how
        if not retailer_id or not product_id:
            missing = [n for n, v in (("retailer", retailer_id), ("product", product_id)) if not v]
            raise InvestigationError("ENTITY_NOT_IDENTIFIED",
                                     f"Could not identify the {' and '.join(missing)} from the question. "
                                     "Mention an ID such as R-104 / P-01 or pick from the selectors.", 422)
        tools.validate_id(retailer_id, tools.RETAILER_ID, "retailer")
        tools.validate_id(product_id, tools.PRODUCT_ID, "product")

        intent = "stockout_investigation"
        if question and not STOCKOUT_WORDS.search(question):
            intent = "stockout_investigation (assumed: only supported intent)"

        now = self.settings.demo_now
        now_dt = datetime.fromisoformat(now)
        since = (now_dt - timedelta(days=self.settings.order_lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")
        ctx = tools.ToolContext(self.client)

        ent = tools.resolve_entities(ctx, retailer_id, product_id)
        if ent["retailer"] is None:
            raise InvestigationError("RETAILER_NOT_FOUND", f"Retailer {retailer_id} was not found in the graph.", 404)
        if ent["product"] is None:
            raise InvestigationError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found in the graph.", 404)

        stock = tools.get_retailer_stock(ctx, retailer_id, product_id)
        network = tools.trace_supply_network(ctx, retailer_id, product_id)
        off_route = tools.find_off_route_stock(ctx, retailer_id, product_id)
        orders = tools.trace_order_fulfillment(ctx, retailer_id, product_id, since)
        route_inv_ids = [n["inventory"]["id"] for n in network if n.get("inventory")]
        reservations = tools.inspect_reservations(ctx, route_inv_ids)
        visits = tools.inspect_sales_visits(ctx, retailer_id, product_id,
                                            (now_dt - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S"))
        promotions = tools.inspect_active_promotions(ctx, product_id, ent["retailer"]["territory"], now[:10])

        bundle = {
            "now": now, "since": since, "lookback_days": self.settings.order_lookback_days,
            "retailer": ent["retailer"], "product": ent["product"], "listed": ent["listed"],
            "retailer_stock": stock, "network": network, "off_route": off_route, "orders": orders,
            "reservations": reservations, "visits": visits, "promotions": promotions,
        }
        analysis = evidence_service.analyse(bundle)

        graph = self._graph(ctx.collector, analysis["path_ids"])
        evidence = self._evidence_cards(ctx.collector, analysis["relevance"], set(analysis["path_ids"]))

        summary_payload = {
            "retailer": ent["retailer"], "product": ent["product"],
            "probable_cause": analysis["probable_cause"], "deterministic_summary": analysis["summary"],
            "observed_facts": [x["statement"] for x in analysis["observed_facts"]],
            "inferences": [x["statement"] for x in analysis["inferences"]],
            "missing_information": [x["item"] for x in analysis["missing_information"]],
        }
        summary, source, note = get_summariser(self.settings).summarise(summary_payload, analysis["summary"])

        return {
            "investigation_id": "INV-" + uuid.uuid4().hex[:8].upper(),
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "demo_clock": now,
            "data_mode": "simulated",
            "question": question,
            "intent": intent,
            "resolved_by": resolved_by,
            "scenario_id": scenario_id,
            "retailer": ent["retailer"],
            "product": {**ent["product"], "listed": ent["listed"]},
            "summary": summary,
            "summary_source": source,
            "summary_note": note,
            "probable_cause": analysis["probable_cause"],
            "stock_summary": self._stock_summary(stock, network, off_route),
            "observed_facts": analysis["observed_facts"],
            "inferences": analysis["inferences"],
            "missing_information": analysis["missing_information"],
            "contradictions": analysis["contradictions"],
            "evidence": evidence,
            "graph": graph,
            "graph_path": graph["path_steps"],
            "recommended_actions": analysis["recommended_actions"],
            "hypothesis_tests": analysis["hypothesis_tests"],
            "query_trace": ctx.trace,
        }

    @staticmethod
    def _stock_summary(stock: list[dict], network: list[dict], off_route: list[dict]) -> dict:
        s = stock[0] if stock else None
        return {
            "retailer": None if s is None else {
                "record_id": s["id"], "quantity": s["quantity"], "reserved": s.get("reserved_quantity", 0),
                "available": evidence_service.available(s), "captured_at": s.get("captured_at")},
            "route": [{
                "distributor_id": n["distributor"]["id"], "distributor": n["distributor"]["name"],
                "warehouse_id": n["warehouse"]["id"], "warehouse": n["warehouse"]["name"], "priority": n["priority"],
                "record_id": n["inventory"]["id"] if n.get("inventory") else None,
                "quantity": n["inventory"]["quantity"] if n.get("inventory") else None,
                "reserved": n["inventory"]["reserved_quantity"] if n.get("inventory") else None,
                "available": evidence_service.available(n.get("inventory")),
            } for n in network],
            "off_route": [{
                "warehouse_id": o["warehouse"]["id"], "warehouse": o["warehouse"]["name"],
                "record_id": o["inventory"]["id"], "available": evidence_service.available(o["inventory"]),
            } for o in off_route],
        }

    @staticmethod
    def _graph(collector: tools.GraphCollector, path_ids: list[str]) -> dict:
        nodes = list(collector.nodes.values())
        edges = collector.edges()
        hl = set(path_ids) & set(collector.nodes)
        hl_edges = [e["id"] for e in edges if e["source"] in hl and e["target"] in hl]
        # Readable chain following the path order, using only edges that the queries returned.
        steps, seen = [], set()
        ordered = [p for p in path_ids if p in hl]
        for i, a in enumerate(ordered):
            for b in ordered[:i][::-1]:
                e = next((e for e in edges if {e["source"], e["target"]} == {a, b} and e["id"] not in seen), None)
                if e:
                    seen.add(e["id"])
                    steps.append({"from": e["source"], "relationship": e["type"], "to": e["target"],
                                  "from_label": collector.nodes[e["source"]]["label"],
                                  "to_label": collector.nodes[e["target"]]["label"]})
                    break
        return {"nodes": nodes, "edges": edges, "highlighted_nodes": sorted(hl), "highlighted_edges": hl_edges,
                "path_steps": steps}

    @staticmethod
    def _evidence_cards(collector: tools.GraphCollector, relevance: dict, path: set) -> list[dict]:
        cards = []
        for nid, n in collector.nodes.items():
            if nid not in relevance and nid not in path:
                continue
            cards.append({
                "record_id": nid,
                "entity_type": n["label"],
                "properties": n["properties"],
                "relevance": relevance.get(nid, "On the highlighted investigation path"),
                "classification": "observed_record",
                "in_path": nid in path,
            })
        cards.sort(key=lambda c: (not c["in_path"], c["entity_type"], c["record_id"]))
        return cards

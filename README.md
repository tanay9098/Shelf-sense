# ShelfSense — Graph-Powered Retail Availability Brain

> **WeMakeDevs × FalkorDB Hackathon 2026 · Track 3: Company Brain**
> ⚠️ **All data is simulated.** Retailers, distributors, warehouses, orders and incidents are fictional. "Surf Excel" appears only as an illustrative product name; nothing here describes a real event involving Hindustan Unilever or any other company.

ShelfSense answers questions like:

> *"Why is Surf Excel unavailable at Sharma Kirana Store (R-104) even though Bhiwandi DC has sufficient inventory?"*

It investigates by **traversing connected records in FalkorDB** — retailer → distributor → warehouse → inventory → product, plus orders, deliveries, reservations, sales visits and promotions — and returns an **evidence-backed answer** that separates *observed facts* from *inferences*, lists *missing or contradictory records*, assigns a *transparent qualitative confidence*, and recommends the *next operational action*.

Change a record (e.g. mark the delayed delivery as delivered) and the investigation re-runs against the graph and the answer changes.

---

## 1. Problem

FMCG distribution managers in general trade see "out of stock at the retailer" while dashboards show stock in a warehouse. The real reason is spread across separate records: was the retailer even on a route to that warehouse? Is the stock *available* or *reserved*? Was an order placed? Was it dispatched? Is the delivery late? Did a delivered shipment get booked into stock? Answering this means joining 5–8 hops of relationships per question — and being honest when the records don't say.

## 2. Why FalkorDB is necessary (not just storage)

Every investigation is a set of **multi-hop graph traversals** executed in FalkorDB:

| Question the system asks | Graph pattern |
|---|---|
| Can this retailer actually get stock from that warehouse? | `(Retailer)-[:SERVED_BY]->(Distributor)-[:SOURCES_FROM]->(Warehouse)-[:HOLDS]->(Inventory)-[:OF_PRODUCT]->(Product)` |
| Is there stock the retailer *can't* reach? | warehouse stock `WHERE NOT (r)-[:SERVED_BY]->()-[:SOURCES_FROM]->(w)` |
| What happened to replenishment? | `(Delivery)-[:FULFILLS]->(Order)-[:FOR_RETAILER]->(Retailer)`, `(Order)-[:FOR_PRODUCT]->(Product)`, `(Order)-[:ALLOCATED_FROM]->(Warehouse)` |
| Who is holding the reserved stock? | `(Order)-[:RESERVES]->(Inventory)<-[:HOLDS]-(Warehouse)` |

The reasoning engine never loads the whole graph; it receives only the rows those queries return (typically 9 queries, ~15–25 ms total, 12–25 records). The dashboard draws exactly the nodes and edges those queries returned — the visual is the query result, not a hard-coded diagram.

## 3. Architecture

```
Browser (vanilla HTML/CSS/JS, SVG graph)
   │  fetch
   ▼
FastAPI  (/api/investigate, /api/demo/mutate, /api/demo/reset, …)
   │
   ▼
InvestigationService ── question → retailer/product (regex IDs, name match,
   │                     graph-assisted disambiguation)
   ▼
Approved investigation tools  (8 fixed, parameterised Cypher templates, ro_query + timeout + LIMIT)
   │
   ▼
FalkorDB  ──►  Node/Edge/Path results
   │
   ▼
GraphCollector (subgraph for UI)  +  EvidenceService (pure rules: facts, inferences,
   │                                  gaps, contradictions, cause, confidence, actions)
   ▼
Deterministic summary  ──(optional)──►  LLM rewrite, validated against returned record IDs
   │
   ▼
Structured JSON → dashboard
```

```
app/
├── main.py                      FastAPI app, exception → structured error mapping, startup seeding
├── config.py                    env settings (.env)
├── api/routes.py                endpoints
├── db/connection.py             FalkorDB client wrapper (timeouts, safe errors)
├── db/schema.py                 labels, relationships, indexes
├── db/seed.py                   deterministic dataset + scenarios, idempotent reset
├── tools/investigation_tools.py approved Cypher tools + subgraph collector
├── services/evidence_service.py rules engine (pure, unit-tested)
├── services/investigation_service.py orchestration & intent routing
├── services/mutation_service.py allow-listed record edits
├── services/llm_service.py      optional provider adapter + output validator
└── models/investigation.py      Pydantic models
static/  index.html · styles.css · app.js · graph.js
tests/   test_graph_logic.py (unit) · test_investigations.py · test_api.py (integration)
scripts/reset_demo.py
docs/    DEMO_SCRIPT.md · SUBMISSION_CHECKLIST.md
```

## 4. Graph schema

Nine labels, 15 relationship types — each one is used by at least one investigation query.

```
(SalesVisit)-[:AT_RETAILER]->(Retailer)-[:SERVED_BY]->(Distributor)-[:SOURCES_FROM {priority}]->(Warehouse)
(SalesVisit)-[:OBSERVED {shelf_status}]->(Product)              (Retailer)-[:LISTS {since}]->(Product)
(Warehouse)-[:HOLDS]->(Inventory)-[:OF_PRODUCT]->(Product)      (Retailer)-[:HOLDS]->(Inventory)
(Order)-[:FOR_RETAILER]->(Retailer)   (Order)-[:FOR_PRODUCT]->(Product)   (Order)-[:ASSIGNED_TO]->(Distributor)
(Order)-[:ALLOCATED_FROM]->(Warehouse)   (Order)-[:RESERVES {quantity}]->(Inventory)
(Delivery)-[:FULFILLS]->(Order)        (Promotion)-[:PROMOTES]->(Product)
```

| Label | Key properties |
|---|---|
| Retailer | id, name, territory, location |
| Product | id, name, brand, category, pack_size |
| Distributor | id, name, territory |
| Warehouse | id, name, territory |
| Inventory | id, quantity, reserved_quantity, available_quantity, captured_at, location_type (`warehouse`/`retailer`) |
| Order | id, quantity, status, ordered_at, promised_at, cancel_reason |
| Delivery | id, status, dispatched_at, expected_at, delivered_at, note |
| SalesVisit | id, visited_at, notes |
| Promotion | id, name, start_date, end_date, status, territory, mechanic |

**Why these relationships**

* `SERVED_BY` + `SOURCES_FROM` model the *replenishment route*. This is what stops the naive conclusion "a warehouse has stock, so the retailer can get it" — off-route stock is reported separately.
* `Inventory` is a node (not a property) so the same snapshot model covers warehouse and retailer stock, carries its own timestamp, and can be the target of `RESERVES`.
* `RESERVES {quantity}` explains *who* holds reserved stock and lets the engine cross-check `reserved_quantity` against actual reservation links (mismatches become contradictions).
* `Delivery` is separate from `Order` because "ordered", "dispatched", "delivered" and "booked into stock" are different facts with different owners.
* `SalesVisit-[:OBSERVED]` gives an independent field observation of the shelf.

Indexes: `CREATE INDEX FOR (n:<Label>) ON (n.id)` for every label.

## 5. Cypher the product depends on

All in `app/tools/investigation_tools.py`, run with `graph.ro_query(query, params, timeout=QUERY_TIMEOUT_MS)`.

**Supply route (4 hops) with available stock computed in the query**
```cypher
MATCH (r:Retailer {id: $retailer_id})-[sb:SERVED_BY]->(d:Distributor)-[sf:SOURCES_FROM]->(w:Warehouse)
OPTIONAL MATCH (w)-[h:HOLDS]->(i:Inventory)-[o:OF_PRODUCT]->(p:Product {id: $product_id})
RETURN r, sb, d, sf, w, h, i, o, p, sf.priority AS priority,
       CASE WHEN i IS NULL THEN null
            WHEN i.quantity - i.reserved_quantity < 0 THEN 0
            ELSE i.quantity - i.reserved_quantity END AS computed_available
ORDER BY d.id, priority ASC LIMIT 25
```

**Stock that exists but is not reachable**
```cypher
MATCH (r:Retailer {id: $retailer_id})
MATCH (w:Warehouse)-[h:HOLDS]->(i:Inventory)-[o:OF_PRODUCT]->(p:Product {id: $product_id})
WHERE NOT (r)-[:SERVED_BY]->(:Distributor)-[:SOURCES_FROM]->(w)
  AND i.quantity - i.reserved_quantity > 0
RETURN w, h, i, o, p, i.quantity - i.reserved_quantity AS computed_available
ORDER BY computed_available DESC LIMIT 10
```

**Order → delivery fulfilment trace**
```cypher
MATCH (o:Order)-[fr:FOR_RETAILER]->(r:Retailer {id: $retailer_id}),
      (o)-[fp:FOR_PRODUCT]->(p:Product {id: $product_id})
WHERE o.ordered_at >= $since
OPTIONAL MATCH (o)-[at:ASSIGNED_TO]->(d:Distributor)
OPTIONAL MATCH (o)-[af:ALLOCATED_FROM]->(w:Warehouse)
OPTIONAL MATCH (del:Delivery)-[f:FULFILLS]->(o)
RETURN o, fr, r, fp, p, at, d, af, w, del, f ORDER BY o.ordered_at DESC LIMIT 20
```

**Who holds the reservations**
```cypher
MATCH (o:Order)-[rs:RESERVES]->(i:Inventory) WHERE i.id IN $inventory_ids
OPTIONAL MATCH (o)-[fr:FOR_RETAILER]->(r:Retailer)
RETURN o, rs, i, fr, r, rs.quantity AS reserved ORDER BY reserved DESC LIMIT 25
```

Other tools: `resolve_entities`, `get_retailer_stock`, `last_order_before_window`, `inspect_sales_visits`, `inspect_active_promotions`. Every executed query, its parameters, row count and duration appear in the **Query trace** panel and in `query_trace` in the API response.

## 6. Investigation workflow

1. **Resolve** retailer and product: explicit IDs (`R-104`, `P-01`), else name matching; if a brand matches several products ("Surf Excel"), the graph disambiguates by which candidate the retailer holds at zero stock. Ambiguity returns a structured 422 with candidates.
2. **Intent**: `stockout_investigation` (the only supported intent; noted as *assumed* when the question doesn't look like one).
3. **Run approved tools** (no generated Cypher).
4. **Normalise** rows into facts (`F1…`) that cite record IDs, and collect the subgraph from the returned `Node`/`Edge` objects.
5. **Rules** (`evidence_service._decide`, ordered): no stockout → active order with delayed/overdue delivery → failed delivery → in-progress delivery → dispatched order with no delivery record → pending order blocked by reserved stock (with alternative route warehouse) → physical shortage → delivered after the stock snapshot (not yet reflected) → depleted after delivery → no route inventory (**undetermined**) → cancelled order → no order on record (**record gap**).
6. **Inferences** (`I1…`) always cite the facts they rest on. **Missing information** lists records that were expected but not returned — explicitly *not* treated as proof of real-world absence. **Contradictions** flag records that disagree (stored vs computed availability, reserved quantity vs `RESERVES` links, delivered delivery on an undelivered order, field visit vs stock record).
7. **Summary**: deterministic template; optionally rewritten by an LLM (see §9) and validated.

### Confidence (qualitative, rule-based — not a probability)

| Level | Rule |
|---|---|
| **High** | A directly linked chain of returned records (order → delivery, or order → reserved inventory) explains the gap, with key timestamps present. |
| **Medium** | Relevant records exist, but a key link, timestamp or confirmation is missing, or the explanation rests on a record that was *not* found. |
| **Low** | Records are insufficient to distinguish competing explanations. |

Each result also lists what evidence would **strengthen** or **weaken** the hypothesis.

## 7. Synthetic dataset & demo scenarios

Deterministic (`random.Random(2026)`, timestamps anchored to `2026-10-15T12:00:00`): **20 retailers, 3 distributors, 3 warehouses, 12 products, 177 inventory snapshots, 112 orders, 109 deliveries (on-time, late-but-delivered, in-transit, scheduled, delayed), 33 sales visits, 4 promotions — 473 nodes, ~1,190 relationships.** The demo clock (`DEMO_NOW`) is fixed so "overdue" is reproducible.

| # | Retailer × Product | Designed situation | Expected result |
|---|---|---|---|
| **A** | R-104 Sharma Kirana × P-01 Surf Excel Easy Wash 1kg | Retailer 0; W-01 1,200 physical / 1,000 available; O-1012 dispatched; DEL-1012 **delayed** (66 h overdue) | *Delayed replenishment delivery* · supported · **high** · ask D-02 to chase DEL-1012 |
| **B** | R-108 Kulkarni Kirana × P-03 Atta 5kg | Retailer 0; W-02 800 available; **no order in 21 days**; visit saw empty shelf | *No replenishment order on record* · record gap · **medium** · no blame assigned |
| **C** | R-112 Sai Krupa Mart × P-05 Soap | W-03 500 physical, **480 reserved** by O-2113/2115/2119 → 20 available < 60 ordered | *Physically present but reserved* · supported · **high** · release reservations or allocate from W-01 (priority-2 route) |
| **D** | R-117 Lokmanya Kirana × P-07 Chips | 13-day-old stock count; route W-02 has **no inventory record**; O-2117 cancelled without reason; stock only off-route at W-03 | *Root cause cannot be determined* · **low** · lists 4 missing records and the next checks |
| E | R-106 × P-06 Toothpaste | O-2106 dispatched, **no delivery record** | *Dispatched order has no delivery record* · record gap · medium |

**Mutation demo (A):** set `DEL-1012` → `delivered` ⇒ result becomes *Delivered stock not yet reflected in retailer inventory* (hypothesis, medium) because the retailer's zero-stock snapshot predates the delivery — the system does **not** assume delivery updates stock. Then set `INV-R-104-P-01` quantity → 48 ⇒ *No stockout recorded*. **Reset to seed data** restores everything.

## 8. Setup

Prerequisites: Python 3.12+, Docker (with Compose).

### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d falkordb          # FalkorDB on :6379, FalkorDB Browser on :3000
python -m scripts.reset_demo           # load the deterministic dataset
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

### Windows (PowerShell)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
docker compose up -d falkordb
python -m scripts.reset_demo
uvicorn app.main:app --port 8000
```

### Everything in Docker
```bash
docker compose --profile app up -d --build   # API + dashboard on http://localhost:8000, seeds on first start
```

If FalkorDB is not running, `/api/health` returns **503** with a diagnostic, the dashboard shows "FalkorDB unavailable", and investigations return `DATABASE_UNAVAILABLE`. There is **no in-memory fallback**.

### Environment variables (`.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `FALKORDB_HOST` / `FALKORDB_PORT` / `FALKORDB_PASSWORD` | localhost / 6379 / empty | Connection |
| `FALKORDB_GRAPH` | shelfsense | Graph key |
| `QUERY_TIMEOUT_MS` | 3000 | Per-query timeout passed to FalkorDB |
| `DEMO_NOW` | 2026-10-15T12:00:00 | Fixed demo clock (IST) |
| `ORDER_LOOKBACK_DAYS` | 21 | Order window |
| `SEED_ON_STARTUP` | true | Seed if graph is empty |
| `LLM_PROVIDER` | none | `none` or `anthropic` |
| `ANTHROPIC_API_KEY` / `LLM_MODEL` | empty / claude-opus-5-5 | Only for `LLM_PROVIDER=anthropic` |
| `CORS_ORIGINS` | localhost:8000 | Allowed origins |

## 9. AI layer (optional, safe by construction)

* Default: **no LLM**. Entity extraction and intent routing are deterministic; summaries are evidence templates.
* With `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`, Claude rewrites the summary from a JSON payload of facts/inferences/gaps. It never sees the database and never writes Cypher.
* The output is **validated**: every record ID it mentions must appear in the evidence, an *undetermined* result must stay undetermined, and length is capped. On any failure, timeout or refusal the deterministic summary is used and the reason is shown (`summary_note`).
* Add a provider by implementing `Summariser.summarise` in `app/services/llm_service.py`.

## 10. API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | App + FalkorDB status and node counts (503 if DB down) |
| GET | `/api/demo/scenarios` | Scenarios + tool catalogue |
| GET | `/api/retailers`, `/api/products` | Selectors |
| POST | `/api/investigate` | `{question?, retailer_id?, product_id?, scenario_id?}` |
| GET | `/api/graph?retailer_id=&product_id=` | Investigation subgraph only |
| GET | `/api/demo/mutations` | Mutation allow-list |
| POST | `/api/demo/mutate` | `{entity_type: Delivery\|Inventory, record_id, field, value, confirm: true}` |
| POST | `/api/demo/reset` | Restore seed data |

Errors are always `{"error": {"code", "message", "details"}}`; no stack traces, credentials or env values are exposed. Interactive docs at `/docs`.

**Mutation allow-list:** `Delivery.status ∈ {scheduled, dispatched, in_transit, delayed, delivered, failed}` (also updates `delivered_at` and the linked `Order.status`); `Inventory.quantity`, `Inventory.reserved_quantity` (integers 0–100,000, reserved ≤ quantity; recomputes `available_quantity`, stamps `captured_at`). Anything else is rejected.

## 11. Tests

```bash
pytest -q                       # unit + integration (integration auto-skips if FalkorDB is unreachable)
pytest -q -m "not integration"  # unit tests only, no database
```

* `tests/test_graph_logic.py` — **unit** (no DB): every rule, confidence downgrades, facts/inference separation, contradiction detection, ID validation & injection strings, mutation allow-list, LLM output validator.
* `tests/test_investigations.py` — **integration** against real FalkorDB on a separate `shelfsense_test` graph, re-seeded per test: all scenarios, reserved-stock arithmetic, grounding (every cited ID exists in the graph with matching properties), mutation → changed result.
* `tests/test_api.py` — health, DB-down handling (real closed port, not a mock), invalid IDs, invalid mutations, reset restores state, dashboard served.

Last local run: **64 passed** (34 unit + 30 integration) with FalkorDB `falkordb/falkordb:latest` in Docker.

## 12. Known limitations

* Single supported intent (stockout investigation); questions are mapped to it.
* Name matching is token-based; unusual phrasing may need IDs or the selectors.
* The demo clock is fixed; there is no real-time data.
* Rules are hand-written for the modelled scenarios. Real networks need more patterns (returns, credit holds, beat-plan misses).
* Retailer stock is a snapshot; the system cannot know true shelf stock between counts — it reports staleness instead.
* The `app` Docker image was written but could not be built in the development environment (Docker Hub rate limit); the FalkorDB service via Compose was verified.
* No authentication — local demo only.

## 13. AI-assisted development disclosure

This project was built with substantial help from an AI coding assistant (Claude Code), which generated most of the code, tests and documentation under the participant's direction. The participant is responsible for the design decisions and must be able to explain the graph model, queries and architecture, as required by the hackathon rules. The optional runtime LLM feature is disabled by default.

## 14. Future improvements

* Persist investigations as `(:Investigation)-[:CITED]->(record)` nodes so the graph remembers past findings.
* Event ingestion (order/delivery webhooks) to replace the fixed demo clock.
* Route-level analytics (e.g. which distributor has the most overdue deliveries) with graph algorithms.
* LLM-assisted intent selection limited to the approved tool catalogue.

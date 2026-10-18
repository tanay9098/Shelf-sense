# ShelfSense — Architecture

> Source of truth is the code. This document was checked against the code on 2026-10-18.
> If you change behaviour described here, update this file and add an entry to `docs/MEMORY.md`.

## 1. Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.12+ | `Dockerfile` uses `python:3.12-slim` |
| Web framework | FastAPI (`>=0.115,<1.0`) + uvicorn | `app/main.py`, `app/api/routes.py` |
| Validation / models | Pydantic v2 | `app/models/investigation.py` |
| Graph database | FalkorDB (Redis protocol, Cypher) | `falkordb` Python client `>=1.8,<2.0`; image `falkordb/falkordb:latest` |
| Config | python-dotenv + env vars | `app/config.py`, `.env.example` |
| Optional LLM | `anthropic` SDK | Only when `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` is set |
| Front end | Vanilla HTML / CSS / JS, hand-written SVG graph renderer | `static/` — no framework, no build step |
| Tests | pytest + httpx (FastAPI `TestClient`) | `tests/` |
| Runtime / infra | Docker Compose (FalkorDB service; optional `app` profile) | `docker-compose.yml`, `Dockerfile` |

## 2. Folder structure

```
Shelf-sense/
├── app/
│   ├── main.py                       FastAPI app, lifespan (ping + seed if empty), CORS, exception → JSON error mapping, serves static/
│   ├── config.py                     Settings dataclass loaded from env (.env)
│   ├── api/routes.py                 All /api endpoints + error() helper
│   ├── db/
│   │   ├── connection.py             GraphClient: FalkorDB wrapper (timeouts, read/write, safe errors, timing)
│   │   ├── schema.py                 Node labels, relationship types, index statements
│   │   └── seed.py                   Deterministic dataset, SCENARIOS, reset_graph, graph_counts, ensure_seeded
│   ├── tools/investigation_tools.py  Approved Cypher templates, ToolContext (runs + traces), GraphCollector, ID validation, TOOL_CATALOGUE
│   ├── services/
│   │   ├── investigation_service.py  Orchestration: entity resolution, intent, tool calls, response assembly
│   │   ├── evidence_service.py       Pure rules engine: facts, inferences, gaps, contradictions, cause, confidence, actions
│   │   ├── mutation_service.py       Allow-listed demo edits with fixed write templates
│   │   └── llm_service.py            Optional summariser + output validator
│   └── models/investigation.py       Request/response Pydantic models
├── static/                           index.html · styles.css · app.js (UI + API calls) · graph.js (SVG subgraph renderer)
├── scripts/reset_demo.py             CLI: reseed the demo graph
├── tests/
│   ├── conftest.py                   Fixtures: separate `shelfsense_test` graph, auto-skip if DB down, DB-down client
│   ├── test_graph_logic.py           Unit (no DB)
│   ├── test_investigations.py        Integration (real FalkorDB)
│   └── test_api.py                   API + integration
├── docs/                             PRD.md · ARCHITECTURE.md · MEMORY.md · RULES.md · DEMO_SCRIPT.md · SUBMISSION_CHECKLIST.md
├── CLAUDE.md / AGENTS.md             Entry point for AI coding tools (points to docs/)
├── docker-compose.yml · Dockerfile · requirements.txt · pytest.ini · .env.example
└── README.md
```

## 3. Component diagram

```
Browser (static/index.html + app.js + graph.js)
   │  fetch JSON
   ▼
FastAPI app (app/main.py)  ── exception handlers → {"error": {code, message, details}}
   │
   ▼
Routes (app/api/routes.py)  ── Pydantic validation (app/models/investigation.py)
   │
   ├─► InvestigationService ──► investigation_tools (8 tools / 9 read-only Cypher queries)
   │        │                         │
   │        │                         ▼
   │        │                   GraphClient.read → FalkorDB ro_query(timeout)
   │        │                         │
   │        │                   GraphCollector (subgraph) + query trace
   │        ▼
   │   evidence_service.analyse (pure rules)  ──►  llm_service (optional, validated)
   │
   ├─► MutationService ──► GraphClient.write (fixed SET templates)
   └─► seed.reset_graph / graph_counts ──► GraphClient.write / read
```

## 4. Database (FalkorDB)

* **Graph key:** `FALKORDB_GRAPH` (default `shelfsense`). Tests use `FALKORDB_TEST_GRAPH` (default `shelfsense_test`), so the demo graph is never touched by tests.
* **Labels (9):** Retailer, Product, Distributor, Warehouse, Inventory, Order, Delivery, SalesVisit, Promotion.
* **Relationships (15):** defined in `app/db/schema.py`.

| Relationship | Meaning |
|---|---|
| `(Retailer)-[:LISTS {since}]->(Product)` | Product is in the retailer's assortment |
| `(Retailer)-[:SERVED_BY]->(Distributor)` | Distributor replenishes the retailer |
| `(Distributor)-[:SOURCES_FROM {priority}]->(Warehouse)` | Replenishment route; priority 1 = primary |
| `(Warehouse)-[:HOLDS]->(Inventory)` | Warehouse stock snapshot |
| `(Retailer)-[:HOLDS]->(Inventory)` | Retailer stock snapshot |
| `(Inventory)-[:OF_PRODUCT]->(Product)` | Product counted by the snapshot |
| `(Order)-[:FOR_RETAILER]->(Retailer)` | Order destination |
| `(Order)-[:FOR_PRODUCT]->(Product)` | Ordered product |
| `(Order)-[:ASSIGNED_TO]->(Distributor)` | Distributor fulfilling the order |
| `(Order)-[:ALLOCATED_FROM]->(Warehouse)` | Source warehouse |
| `(Order)-[:RESERVES {quantity}]->(Inventory)` | Reservation on warehouse stock |
| `(Delivery)-[:FULFILLS]->(Order)` | Shipment executing the order |
| `(SalesVisit)-[:AT_RETAILER]->(Retailer)` | Field visit location |
| `(SalesVisit)-[:OBSERVED {shelf_status}]->(Product)` | Shelf observation |
| `(Promotion)-[:PROMOTES]->(Product)` | Trade promotion |

* **Key properties:** see README §4. `Inventory.available_quantity` is stored, but the queries also compute `quantity - reserved_quantity` so stored-vs-computed mismatches can be flagged as contradictions.
* **Indexes:** `CREATE INDEX FOR (n:<Label>) ON (n.id)` for every label.
* **Seeding:** `seed._build_dataset()` is deterministic (`random.Random(2026)`, timestamps relative to `DEMO_NOW`). `reset_graph` deletes the graph and recreates it (473 nodes: 20 retailers, 3 distributors, 3 warehouses, 12 products, 177 inventory snapshots, 112 orders, 109 deliveries, 33 sales visits, 4 promotions). `ensure_seeded` seeds on startup only if the graph is empty and `SEED_ON_STARTUP=true`.
* **Connection rules (`GraphClient`):** socket timeout 5 s, connect timeout 2 s, per-query timeout `QUERY_TIMEOUT_MS`; connection errors → `DatabaseUnavailable` (503); query errors → `QueryFailed` (502); missing graph → `GraphMissing`.

## 5. Investigation tools

8 approved tools in `TOOL_CATALOGUE`; they execute **9 read-only queries** because
`trace_order_fulfillment` runs a second query, traced as `last_order_before_window`.

| Tool | Query | Notes |
|---|---|---|
| `resolve_entities` | `Q_RESOLVE` | Retailer, product, LISTS edge |
| `get_retailer_stock` | `Q_RETAILER_STOCK` | LIMIT 5, newest first |
| `trace_supply_network` | `Q_SUPPLY_NETWORK` | 4-hop route, LIMIT 25 |
| `find_off_route_stock` | `Q_OFF_ROUTE_STOCK` | Available stock not reachable via routes, LIMIT 10 |
| `trace_order_fulfillment` | `Q_ORDERS_RECENT` + `Q_ORDER_LAST_BEFORE` | Orders in lookback window (LIMIT 20) + last order before it (LIMIT 1) |
| `inspect_reservations` | `Q_RESERVATIONS` | **Skipped (no query) when no route warehouse holds the product** → 8 queries in that case |
| `inspect_sales_visits` | `Q_SALES_VISITS` | Last 14 days, LIMIT 10 |
| `inspect_active_promotions` | `Q_PROMOTIONS` | Active on demo date in territory or 'All', LIMIT 10 |

When a free-text question is resolved by name, `list_retailers` / `list_products` run two extra
read queries before the investigation; these are not part of `query_trace`.

## 6. API flow

### Endpoints

| Method | Path | Handler → service |
|---|---|---|
| GET | `/` | `static/index.html` |
| GET | `/api/health` | ping + `seed.graph_counts`; 200, or 503 if DB down |
| GET | `/api/demo/scenarios` | `seed.SCENARIOS` + `TOOL_CATALOGUE` |
| GET | `/api/retailers`, `/api/products` | `list_retailers` / `list_products` |
| POST | `/api/investigate` | `InvestigationService.investigate` |
| GET | `/api/graph?retailer_id=&product_id=` | Runs the **full** investigation (incl. optional LLM summary) and returns only `graph` |
| GET | `/api/demo/mutations` | `describe_allowlist` |
| POST | `/api/demo/mutate` | `MutationService.apply` |
| POST | `/api/demo/reset` | `seed.reset_graph` |
| GET | `/docs` | FastAPI OpenAPI UI |

### `POST /api/investigate` step by step

1. **Validate request** — `InvestigateRequest`: question ≤ 500 chars, ID patterns, need question / scenario / both IDs.
2. **Resolve entities** — scenario → its IDs; else free-text question → `resolve_question` (regex IDs, token name match, graph-assisted product disambiguation; ambiguity → 422 with candidates); else explicit IDs.
3. **Validate IDs** — `validate_id` against `R-\d{3}` / `P-\d{2}`.
4. **Intent** — always `stockout_investigation` (marked *assumed* if the question does not look like a stock-out question).
5. **Run tools** — via `ToolContext.run` → `GraphClient.read` (`ro_query` with timeout). Each run adds rows to the `GraphCollector` and a `query_trace` entry.
6. **Analyse** — `evidence_service.analyse(bundle)`: facts `F1…`, inferences `I1…`, missing info, contradictions, probable cause (ordered rules in `_decide`), confidence, actions, hypothesis tests.
7. **Summarise** — deterministic template; if enabled, `AnthropicSummariser` rewrites it and `validate_summary` checks IDs / undetermined status / length, else falls back.
8. **Respond** — `InvestigationResponse` JSON: summary, probable_cause, stock_summary, facts, inferences, missing_information, contradictions, evidence, graph, graph_path, recommended_actions, hypothesis_tests, query_trace.

### `POST /api/demo/mutate`

`MutationRequest` → `confirm` must be true (else `CONFIRMATION_REQUIRED` 400) → allow-list check
(`FIELD_NOT_ALLOWED` / `INVALID_VALUE` 422) → fetch record (`RECORD_NOT_FOUND` 404) → fixed `SET`
template. Delivery status also updates `delivered_at` and the linked `Order.status`; inventory
edits recompute `available_quantity` and stamp `captured_at` (reserved > quantity → `INCONSISTENT_VALUE`).

### Error mapping (`app/main.py`)

| Exception | Code | HTTP |
|---|---|---|
| `DatabaseUnavailable` | `DATABASE_UNAVAILABLE` | 503 |
| `QueryFailed` | `QUERY_FAILED` | 502 |
| `InvestigationError` | its own code | its own status |
| `MutationError` | its own code | its own status |
| `InvalidIdentifier` | `INVALID_ID` | 422 |
| `RequestValidationError` | `VALIDATION_ERROR` | 422 |
| any other | `INTERNAL_ERROR` | 500 |

## 7. Configuration

All variables are in `.env.example` and read in `app/config.py`:
`FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_PASSWORD`, `FALKORDB_GRAPH`, `QUERY_TIMEOUT_MS`,
`DEMO_NOW`, `ORDER_LOOKBACK_DAYS`, `SEED_ON_STARTUP`, `LLM_PROVIDER`, `ANTHROPIC_API_KEY`,
`LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `CORS_ORIGINS`. Tests additionally read `FALKORDB_TEST_GRAPH`.

## 8. Design decisions

* **No generated Cypher.** Only fixed, parameterised templates — prevents injection and keeps results explainable.
* **Inventory as a node.** One model for warehouse and retailer stock, with its own timestamp, and a target for `RESERVES`.
* **Delivery separate from Order.** Ordered, dispatched, delivered and booked-into-stock are different facts.
* **Rules engine is pure.** `evidence_service` takes a dict and returns a dict, so it is unit-tested without a database.
* **No fake fallback.** If FalkorDB is down the API says so (503) instead of returning invented results.

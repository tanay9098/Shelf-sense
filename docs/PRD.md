# ShelfSense — Product Requirements Document (PRD)

> Status: MVP built for the WeMakeDevs × FalkorDB Hackathon 2026 (Track 3: Company Brain).
> All data is simulated. See `README.md` for setup and `docs/ARCHITECTURE.md` for how it is built.

## 1. Problem

In FMCG general-trade distribution, a retailer (e.g. a kirana store) is out of stock of a product
while dashboards show that a warehouse holds plenty of it. The real reason is scattered across
separate records — replenishment routes, stock snapshots, reservations, orders, deliveries, field
visits and promotions. Finding it means manually joining 5–8 hops of relationships, and people
often jump to conclusions the records do not support.

## 2. Goal

Answer *"Why is product X unavailable at retailer Y?"* with an **evidence-backed** explanation that:

* cites the exact records it is based on,
* separates observed facts from inferences,
* states what is missing or contradictory instead of guessing,
* gives a transparent, rule-based confidence level, and
* recommends the next operational action.

## 3. Target users

| User | Need |
|---|---|
| **Distribution / area sales manager** (primary) | Understand why a retailer is out of stock and who should act. |
| **Distributor operations staff** | See which order or delivery is stuck and chase it. |
| **Field sales representative** | Turn an empty-shelf observation into a concrete, explained issue. |
| **Supply-chain analyst** | Inspect the graph traversal and query trace behind an answer. |
| **Hackathon judges** (secondary) | See FalkorDB doing real multi-hop work, with clear evidence. |

## 4. Features (MVP)

| # | Feature | Where |
|---|---|---|
| F1 | Ask in plain English, or pick a retailer + product, or pick a demo scenario (A–E) | `static/`, `POST /api/investigate` |
| F2 | Entity resolution from IDs (`R-104`, `P-01`) or names; graph-assisted disambiguation of ambiguous products | `investigation_service.resolve_question` |
| F3 | Investigation through 8 approved, parameterised Cypher tools (9 read-only queries) | `app/tools/investigation_tools.py` |
| F4 | Result split into observed facts, inferences, missing information and contradictions, each citing record IDs | `app/services/evidence_service.py` |
| F5 | Probable cause with status (supported / hypothesis / record gap / undetermined) and qualitative confidence (high / medium / low) | `evidence_service._decide` |
| F6 | Recommended next actions and evidence that would strengthen / weaken the hypothesis | `evidence_service` |
| F7 | Investigation subgraph visual (only nodes/edges the queries returned) and query trace panel | `static/graph.js`, `query_trace` |
| F8 | Edit an allow-listed simulated record (delivery status, inventory quantities) and re-run | `POST /api/demo/mutate` |
| F9 | Reset demo data to the deterministic seed | `POST /api/demo/reset`, `scripts/reset_demo.py` |
| F10 | Optional LLM rewrite of the summary, validated against the evidence; deterministic fallback | `app/services/llm_service.py` |
| F11 | Health endpoint and clear "FalkorDB unavailable" state | `GET /api/health` |

## 5. Functional requirements

1. **FR-1** Accept a question (≤ 500 chars), a `scenario_id`, or both `retailer_id` and `product_id`; reject otherwise with `VALIDATION_ERROR` (422).
2. **FR-2** IDs must match `R-\d{3}` (retailer) and `P-\d{2}` (product); invalid IDs return `INVALID_ID` / `VALIDATION_ERROR` (422).
3. **FR-3** If the retailer or product cannot be identified, return `ENTITY_NOT_IDENTIFIED` (422); if ambiguous, return `AMBIGUOUS_RETAILER` / `AMBIGUOUS_PRODUCT` (422) with candidates; an unknown scenario returns `UNKNOWN_SCENARIO` (404); if not in the graph, return `RETAILER_NOT_FOUND` / `PRODUCT_NOT_FOUND` (404).
4. **FR-4** Only the fixed Cypher templates may be executed. No user or LLM text is ever concatenated into a query.
5. **FR-5** Every fact must cite at least one record ID returned by a query; every inference must cite the facts it rests on.
6. **FR-6** Missing records are reported as *missing information*, never as proof of real-world absence.
7. **FR-7** Confidence follows the documented rules (README §6); it is never presented as a probability.
8. **FR-8** Mutations are limited to the allow-list (`Delivery.status`, `Inventory.quantity`, `Inventory.reserved_quantity`), require `confirm: true`, and keep derived fields consistent.
9. **FR-9** Reset restores the exact seed dataset.
10. **FR-10** If the LLM is disabled, fails, refuses, or produces a summary citing unknown IDs, the deterministic summary is used and the reason is reported in `summary_note`.
11. **FR-11** If FalkorDB is unreachable, return `DATABASE_UNAVAILABLE` (503). There is no in-memory or fake fallback.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Each query has a timeout (`QUERY_TIMEOUT_MS`, default 3000 ms) and a `LIMIT`; an investigation typically completes in ~15–25 ms of DB time. |
| Determinism | Seed uses `random.Random(2026)` and a fixed demo clock (`DEMO_NOW`), so results are reproducible. |
| Safety | Read-only queries (`ro_query`) for investigations; allow-listed writes only for demo mutations. |
| Error handling | All errors use `{"error": {"code", "message", "details"}}`; no stack traces, credentials or env values are exposed. |
| Transparency | Every executed query, its parameters, row count and duration are returned in `query_trace`. |
| Data | Simulated data only, clearly labelled in UI and API (`data_mode: "simulated"`). |
| Dependencies | Minimal: FastAPI, uvicorn, falkordb, pydantic, python-dotenv; `anthropic` optional; no front-end build step. |
| Testability | Unit tests run without a database; integration tests run against real FalkorDB on a separate graph. |

## 7. Out of scope (non-goals)

* Authentication, authorisation, multi-tenant use.
* Real-time data ingestion; the demo clock is fixed.
* Intents other than stock-out investigation.
* Real customer or company data.
* LLM-generated Cypher or LLM access to the database.

## 8. Success criteria

* Scenarios A–E return their expected cause, status and confidence (README §7).
* The mutation demo changes the result as described (DEL-1012 → delivered; inventory 48 → no stockout) and reset restores it.
* Every record ID cited in a response exists in the graph with matching properties (integration test).
* `pytest -q` passes (64 tests: 34 unit + 30 integration with FalkorDB running).

## 9. Future scope

See README §15 — persisted investigations, event ingestion, route analytics, LLM-assisted intent selection limited to the approved tool catalogue.

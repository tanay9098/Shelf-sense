# ShelfSense — Project Memory

> **Read this first.** It lets a new developer or AI tool continue without reading the whole
> codebase. Open only the files it points to. Keep it current: add a change-log entry after
> every change (see `docs/RULES.md` §5).

## 1. Current state (2026-10-18)

* MVP complete: stock-out investigation over FalkorDB, dashboard, demo mutations, reset, optional LLM summary.
* Only intent supported: `stockout_investigation`.
* Tests: 64 collected (34 unit + 30 integration). Unit tests pass without a DB; integration tests need FalkorDB.
* Docker image for the `app` service was never verified to build (Docker Hub rate limit); the FalkorDB compose service was verified.
* Hackathon submission window ends 18 Oct 2026 11:59 PM IST — see `docs/SUBMISSION_CHECKLIST.md`.

## 2. Where things are

| I want to change… | Go to |
|---|---|
| An endpoint | `app/api/routes.py` (+ models in `app/models/investigation.py`) |
| A Cypher query / add a tool | `app/tools/investigation_tools.py` (+ `TOOL_CATALOGUE`) and call it in `investigation_service.py` |
| How a cause/confidence is decided | `app/services/evidence_service.py` (`analyse`, `_decide`) |
| Name/ID resolution of questions | `app/services/investigation_service.py` (`resolve_question`) |
| Allowed demo edits | `app/services/mutation_service.py` (`ALLOWLIST`) |
| Demo data or scenarios | `app/db/seed.py` (`_build_dataset`, `SCENARIOS`) |
| Schema (labels/relationships) | `app/db/schema.py` |
| DB connection / timeouts / errors | `app/db/connection.py` |
| Env settings | `app/config.py`, `.env.example` |
| UI | `static/app.js` (logic), `static/graph.js` (SVG graph), `static/index.html`, `static/styles.css` |

Full detail: `docs/ARCHITECTURE.md`. Product scope: `docs/PRD.md`. Rules: `docs/RULES.md`.

## 3. Key facts to remember

* Demo clock is fixed: `DEMO_NOW=2026-10-15T12:00:00`; order lookback 21 days; visits lookback 14 days.
* Seed: `random.Random(2026)` → 473 nodes (~1,190 relationships). Reset with `python -m scripts.reset_demo` or `POST /api/demo/reset`.
* ID formats: retailer `R-###`, product `P-##`, other records `^[A-Z]{1,3}-[A-Z0-9-]{2,20}$` (e.g. `O-1012`, `DEL-1012`, `INV-R-104-P-01`).
* Scenarios: A = R-104 × P-01 delayed delivery DEL-1012 · B = R-108 × P-03 no order · C = R-112 × P-05 reserved stock · D = R-117 × P-07 undetermined · E = R-106 × P-06 dispatched order without delivery record.
* Mutation demo: DEL-1012 → delivered ⇒ "delivered stock not yet reflected"; INV-R-104-P-01 quantity 48 ⇒ no stockout.
* 8 tools, 9 read-only queries per investigation (8 when no route inventory exists, because `inspect_reservations` is skipped).
* `GET /api/graph` runs the full investigation (including the optional LLM call) and returns only the graph.
* Tests use a separate graph `shelfsense_test` (`FALKORDB_TEST_GRAPH`), re-seeded per test.
* LLM is off by default (`LLM_PROVIDER=none`). With `anthropic`, it only rewrites the summary and is validated.

## 4. Decisions (and why)

| Decision | Reason |
|---|---|
| Fixed Cypher templates only | Safety (no injection) and explainability |
| Inventory modelled as a node | Same model for warehouse/retailer stock, timestamps, `RESERVES` target |
| Delivery separate from Order | Ordered / dispatched / delivered / booked are different facts |
| Qualitative confidence, not % | Rule-based and explainable; avoids fake precision |
| No in-memory fallback | Never show invented results |
| Vanilla JS front end | No build step, no extra dependencies |

## 5. Known gaps / open items

* Single intent; token-based name matching may miss unusual phrasing.
* No authentication (local demo only).
* `falkordb/falkordb:latest` is not pinned in `docker-compose.yml`.
* LLM path verified only for failure/fallback, not with a real key.
* `GET /api/graph` does more work than needed (full investigation) — possible optimisation, but keep the response unchanged.

## 6. Change log

Newest first. Format: `YYYY-MM-DD — what changed — files — tests run / result`.

* **2026-10-18** — Added project docs: `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/RULES.md`, `docs/MEMORY.md`, `CLAUDE.md`, `AGENTS.md`. Fixed README inconsistencies (tool vs query count, `last_order_before_window` described as a sub-query, `/api/graph` behaviour, missing `LLM_TIMEOUT_SECONDS`) and the wrong `docker compose up -d --build` comment in `docker-compose.yml`. No code changes. — `pytest -q`: 34 passed, 30 skipped (FalkorDB not available in the environment).
* **2026-10-17** — Initial ShelfSense MVP (commit `ae55b3e`).

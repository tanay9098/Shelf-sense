# ShelfSense — Development Rules

These rules apply to every change, whether made by a person or an AI coding tool.
If a change needs to break one of them, stop and ask the project owner first.

## 1. No unnecessary dependencies

* Do **not** add a package to `requirements.txt` unless the change cannot reasonably be done with
  the standard library or the existing dependencies (FastAPI, uvicorn, falkordb, pydantic,
  python-dotenv, anthropic [optional], pytest, httpx).
* If a new dependency is truly needed: give it a version range, explain why in the commit message,
  and record it in `docs/MEMORY.md`.
* The front end stays vanilla HTML/CSS/JS: no framework, bundler, npm or CDN libraries.
* Optional features (like the LLM) must keep their dependency optional — import it lazily and
  fall back cleanly when it is missing.

## 2. Don't break existing APIs

* Keep every existing endpoint path and method in `app/api/routes.py` working.
* Do not rename or remove request/response fields, error codes or HTTP status codes. Changes must
  be **additive** (new optional fields, new endpoints).
* Keep the error shape `{"error": {"code", "message", "details"}}` for every error.
* If something must be removed, mark it deprecated first, document it in `docs/ARCHITECTURE.md`
  and `docs/MEMORY.md`, and get the owner's approval.
* The front end (`static/app.js`) is an API consumer — check it still works after any API change.
* Do not change the graph schema (labels, relationship types, key properties) in a way that
  breaks the existing Cypher templates or the seed scenarios A–E.

## 3. Test after every change

* After **every** change run:
  ```bash
  pytest -q                       # full suite (start FalkorDB first: docker compose up -d falkordb)
  pytest -q -m "not integration"  # minimum, when FalkorDB is not available
  ```
* All tests must pass before committing. Integration tests auto-skip when FalkorDB is down —
  say so explicitly in the commit/PR if they were skipped.
* New logic needs new or updated tests (rules → `tests/test_graph_logic.py`; queries and
  scenarios → `tests/test_investigations.py`; endpoints → `tests/test_api.py`).
* For UI changes, also run the app (`uvicorn app.main:app --port 8000`) and check scenarios A–E,
  the mutation demo and reset.
* Never skip, disable or delete a test to get a green run.
* Record the test result in the change log in `docs/MEMORY.md`.

## 4. Project-specific rules

* **Cypher:** only fixed, parameterised templates in `app/tools/` or `app/services/mutation_service.py`.
  Never concatenate user or LLM text into a query. Investigation queries use `GraphClient.read`
  (read-only) and must have a `LIMIT`.
* **Evidence:** every fact cites record IDs; every inference cites facts; missing records are
  reported as gaps, not as proof.
* **Mutations:** only via the allow-list in `mutation_service.ALLOWLIST`.
* **No fake data fallback:** if FalkorDB is down, return `DATABASE_UNAVAILABLE` (503).
* **Data:** simulated only. No real customer data, no claims about real companies.
* **Secrets:** never commit `.env` or keys; `.env.example` holds placeholders only. Never expose
  stack traces, credentials or env values in API responses.
* **Determinism:** keep `random.Random(2026)` and `DEMO_NOW` so scenarios stay reproducible.
* **Style:** match the surrounding code (type hints, short docstrings, small functions).

## 5. Documentation duties

After a change, update whichever of these it affects:

* `docs/MEMORY.md` — **always**: add a change-log entry.
* `docs/ARCHITECTURE.md` — structure, flow, schema, endpoints, config.
* `docs/PRD.md` — features or requirements.
* `README.md` — setup, env variables, API table, test counts.

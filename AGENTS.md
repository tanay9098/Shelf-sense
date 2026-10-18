# ShelfSense — guide for AI coding tools

Before doing anything, read these in order:

1. `docs/MEMORY.md` — current state, where things are, key facts, change log. Start here instead of reading the whole codebase.
2. `docs/RULES.md` — must follow: no unnecessary dependencies, don't break existing APIs, test after every change.
3. `docs/ARCHITECTURE.md` — tech stack, folder structure, database, API flow.
4. `docs/PRD.md` — features, target users, requirements.

Quick commands:

```bash
pip install -r requirements.txt
docker compose up -d falkordb && python -m scripts.reset_demo
uvicorn app.main:app --reload --port 8000
pytest -q                        # or: pytest -q -m "not integration" without FalkorDB
```

After every change: run the tests, update the docs affected, and add an entry to the change log in `docs/MEMORY.md`.

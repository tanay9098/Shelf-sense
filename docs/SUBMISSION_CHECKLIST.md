# Submission checklist

Requirements below are from https://www.wemakedevs.org/hackathons/falkordb/rules as read on 2026-10-17. **Re-check the official rules page before submitting** — requirements and deadlines may change.

Submission window (as read): **15 Oct 2026 12:01 AM IST → 18 Oct 2026 11:59 PM IST.**

## Required by the rules (as read)
- [ ] FalkorDB is the primary graph database and does real work (multi-hop investigation queries) — README §2, §5
- [ ] Public source-code repository (make `tanay9098/Shelf-sense` public, or push to a public repo)
- [ ] README with setup instructions and graph data model — README §4, §8
- [ ] Cypher queries the product depends on — README §5 and `app/tools/investigation_tools.py`
- [ ] Demo video of the working project (follow `docs/DEMO_SCRIPT.md`, 3–4 min)
- [ ] Live deployment **or** complete local setup instructions — README §8
- [ ] Track(s) named at submission: **Company Brain** (optionally also "Agents That Act on Connected Data")
- [ ] AI-assistant use disclosed — README §13
- [ ] You can explain the graph model, queries, architecture and decisions yourself (rules say fully AI-generated projects without meaningful contribution may be rejected) — rehearse README §2–§7
- [ ] Main work done during the hackathon window

## Before recording / submitting
- [ ] `docker compose up -d falkordb` → `python -m scripts.reset_demo` → `uvicorn app.main:app` works from a fresh clone
- [ ] `pytest -q` → all pass with FalkorDB running (64 tests at time of writing)
- [ ] Dashboard header shows **FalkorDB connected** and **Simulated Demo Data**
- [ ] Scenarios A–E give: delayed delivery / no order / reserved stock / undetermined / missing delivery record
- [ ] Mutation demo: DEL-1012 → delivered changes the result; inventory 48 → no stockout; Reset restores
- [ ] Stop the server with FalkorDB down once and confirm the 503 diagnostic appears (no fake results)
- [ ] `.env` is **not** committed; `.env.example` contains placeholders only
- [ ] No real customer data, no real-company incident claims; disclaimer visible in UI footer and README
- [ ] Optional: pin the FalkorDB image tag in `docker-compose.yml` to the version you tested
- [ ] Optional: verify `docker compose --profile app up -d --build` (not verified in the dev environment due to a Docker Hub rate limit)
- [ ] Optional: if enabling `LLM_PROVIDER=anthropic`, test with a real key (only the failure/fallback path was verified)
- [ ] Add screenshots / GIF to README (optional but helpful for judges)

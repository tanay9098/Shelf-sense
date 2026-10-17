# ShelfSense — 3½-minute demo script

**Before recording:** `docker compose up -d falkordb && python -m scripts.reset_demo && uvicorn app.main:app --port 8000`. Open http://localhost:8000 at 1440 px wide. Optionally open FalkorDB Browser at http://localhost:3000 in a second tab. Check the header says **FalkorDB connected · 473 nodes**.

---

### 0:00 – 0:25 · The problem
> "In Indian general trade, a distribution manager often hears 'the kirana store is out of Surf Excel' while the dashboard says the warehouse has a thousand units. The answer is scattered across routes, stock snapshots, reservations, orders and deliveries. ShelfSense investigates that with FalkorDB. Everything you'll see is simulated data — note the badge."

Point at **Simulated Demo Data** and **FalkorDB connected**.

### 0:25 – 1:10 · Ask the question (Scenario A)
Click scenario **A – Stock in warehouse, delivery delayed** (or type *"Why is Surf Excel unavailable at Sharma Kirana Store?"* and press Investigate — the graph disambiguates which Surf Excel SKU).

> "Answer: delayed replenishment delivery — supported by records, high confidence. Retailer shows 0; Bhiwandi DC has 1,200 physical, 200 reserved, 1,000 available. So supply isn't the problem — delivery DEL-1012 for order O-1012 is 66 hours overdue."

Point at the **Stock position** table and **Recommended next actions** (chase DEL-1012 with Konkan Trade Links; emergency replenishment if ETA isn't credible).

### 1:10 – 1:50 · Show the graph traversal and evidence
Scroll to **Investigation subgraph**.
> "This isn't a drawing — it's exactly the nodes and edges the queries returned. Highlighted path: R-104 SERVED_BY D-02, SOURCES_FROM W-01, HOLDS the inventory, and the order with its FULFILLS delivery. Off-route warehouses are shown dimmed: stock exists there but no recorded route connects them to this retailer."

Click a fact chip such as **DEL-1012** → the node is selected in the graph. Open **Query trace**:
> "Nine parameterised Cypher queries, about 20 milliseconds in FalkorDB. No LLM-generated Cypher."

### 1:50 – 2:20 · Facts vs inferences vs uncertainty
> "Observed facts restate returned records and cite IDs. Inferences cite the facts they depend on. Confidence is a documented rule, not a fake percentage. And here's what would strengthen or weaken the hypothesis."

Quickly click scenario **D – Insufficient evidence**:
> "When the records don't explain it, ShelfSense says so: low confidence, and it lists the missing evidence — no inventory record on the route warehouse, a cancelled order with no reason, a 13-day-old stock count — and what to check next."

### 2:20 – 3:10 · Change the graph, re-run
Click scenario **A** again. In **Change a simulated record**, set **DEL-1012 → delivered**, click **Apply & re-run**, confirm.
> "The record is written to FalkorDB and every query runs again. Before: delayed delivery. After: *delivered stock not yet reflected in retailer inventory* — a hypothesis, medium confidence. It doesn't assume a delivery magically updates shelf stock: the zero-stock snapshot was taken before the delivery."

Then set **INV-R-104-P-01** physical qty → **48**, apply.
> "After a recount, no stockout is recorded."

Click **Reset to seed data** and confirm.

### 3:10 – 3:30 · Why the graph matters
> "Each answer needed 4–6 hops: retailer to distributor to warehouse to inventory, order to delivery, order to reservation. Relationships are what let ShelfSense tell 'stock exists' from 'stock is reachable and available', and tell a delivery problem from an ordering gap — with evidence for every claim."

*Optional extra (if time): Scenario C — 500 physical vs 480 reserved, the reservation holders found through `RESERVES`, and the secondary route warehouse W-01 recommended.*

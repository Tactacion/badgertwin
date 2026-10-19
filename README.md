# LoopWatch

A digital twin of UW–Madison's campus chilled-water network. It replays the **June 17, 2026 main break** ($15.8M, 34 buildings) on simulated data built from public facts:

1. **Catch the leak early.** Make-up water starts rising on Jun 7. The detector alerts **Jun 8 13:00, 217 hours before the burst**, rejects a planted sensor glitch, and ranks the 1966 Charter main **CW-M01** first.
2. **Plan the emergency.** When the main is shut off, a mixed-integer optimizer decides which buildings get plant water, where rented chillers go, and which buildings close. It solves in under a second, and judges can change the heat, the outage size or the budget live.
3. **Humans approve.** Agents draft the diagnosis, work order, campus alert and Regents request. A named person approves anything that changes the system or spends money, and every step lands in the audit log.

> **Simplified, simulated data built from public facts.** The pipe network is approximate and is not UW's real network. See [LOOPWATCH_C3_PLAYBOOK.md](LOOPWATCH_C3_PLAYBOOK.md) §12 for what is real, estimated and simulated.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
(cd ui && npm install && npm run build)                  # builds the React app into badgertwin/web_dist
.venv/bin/uvicorn badgertwin.server:app --port 8765      # open http://localhost:8765
.venv/bin/python -m pytest -q                            # 23 tests
```

To work on the UI with hot reload, run `cd ui && npm run dev` (it proxies `/api` to port 8765).

Demo links:
- `/?skip&t=2026-06-14%2012:00` shows the growing leak.
- `/?skip&t=2026-06-17%2016:00` shows the burst.
- `/?skip&tab=plan` opens the emergency plan.
- `/classic` opens the old plain-HTML UI.

**UI:** React, Tailwind, shadcn/ui, MapLibre and Motion. The map is the real campus, using Esri satellite imagery and OpenFreeMap 3D buildings, with no API keys. Our 50 buildings are their real OpenStreetMap footprints. Pipe width follows the flow, and each water dot moves at the simulated water speed.

## Layout

| Path | What |
|---|---|
| `badgertwin/data.py` | Loads the dataset. Defines the scenario times and the load-factor formula |
| `badgertwin/leak.py` | **Tool 1**: water-balance detector, pipe localisation, sensor-fault guard, `scan()` scoring |
| `badgertwin/health.py` | **Tool 2**: transparent 10-year failure risk for pipes, chillers and pumps |
| `badgertwin/planner.py` | **Tool 3**: emergency cooling MILP (scipy HiGHS) with greedy fallback and a 72-h temperature replay |
| `badgertwin/repairs.py` | **Tool 5**: expected loss via max-flow, plus a knapsack within budget |
| `badgertwin/agents.py` | Monitoring, diagnosis, work order, campus alert, Regents request and cited Q&A (deterministic) |
| `badgertwin/store.py` | Approvals and audit log (named approvers, two-person plan approval) |
| `badgertwin/server.py` | FastAPI: the API and the built UI |
| `ui/` | React + shadcn/ui app (map, agents panel, timeline, plan) |
| `badgertwin/web/` | Older plain-HTML UI (`/classic`) |
| `scripts/build_twin_data.py` | Rebuilds `data/simulated/` (EPANET replay via WNTR, seed 1980) |
| `scripts/export_c3_package.py` | Generates the C3 package in `c3/badgerTwin/` |
| `c3/badgerTwin/` | **C3 package**: Types, seed data, Python methods and vendored core. See [C3_IMPORT.md](C3_IMPORT.md) |
| `data/` | `raw/` downloads, `curated/` cited facts, `simulated/` twin, `c3_upload/` small CSVs for C3 Code chat |

## Key numbers (from the code, not hand-typed)

| | |
|---|---|
| Leak alert lead time | 217 h (Jun 8 13:00 → Jun 17 14:00), 0 false alarms, glitch rejected |
| East-zone load (34 buildings) | 11,691 design tons ≈ 30 rented chillers × 300–500 t |
| Rental cost model | P50 $162K/day (P10 $134K, P90 $196K) vs UW's $10M ÷ 43–64 days |
| Planner at 95 °F | about 0.5 s, patient care always 100%, closures only where a rental isn't worth it |

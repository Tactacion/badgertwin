# Getting BadgerTwin into your C3 Code workspace

The working app and its logic live in this repo, and `c3/badgerTwin/` is the same thing packaged for C3. C3 Code workspaces are Git-backed, with one branch per workspace ([docs](https://docs.c3.ai/docs/genesis/8.10/topic/c3code-overview)). The plan is to put the repo on GitHub, bring it into the workspace, and let C3 Code adapt the few platform-specific lines.

> ⚠️ **Not verified on your platform version:** the Python runtime tag in `BadgerTwin.c3typ` (`py-server`), the seed-file format, and the `c3.<Type>.fetch()` call in `BadgerTwin.py`. These are the only platform-specific spots. C3 Code fixes them in one or two messages.

## 1. Put the repo on GitHub

Claude can do this for you (`gh repo create … --private --push`). Or run it yourself:

```bash
git remote add origin https://github.com/<you>/badgertwin.git && git push -u origin main
```

## 2. Bring it into the workspace (pick whichever works)

- **A. GitHub connection.** In C3 Code, connect GitHub (OAuth) and point the workspace at the repo/branch, or merge `main` into the workspace branch.
- **B. Code mode (browser VS Code).** Open a terminal and run `git pull https://github.com/<you>/badgertwin.git main`, or `git remote add` it and merge.
- **C. Upload.** Zip `c3/badgerTwin/` and attach it in chat with the prompt below.

## 3. Then paste this into the C3 Code chat (short on purpose)

```text
This workspace now contains a ready C3 package at c3/badgerTwin (generated from a tested Python app).
Do not redesign it. Make it build and run on this platform, in this order, and stop after each step:

1. Make the package build: fix the manifest (badgerTwin.c3pkg.json), the .c3typ syntax and the Python
   method runtime tag in src/app/BadgerTwin.c3typ for this platform version. Don't rename types or fields.
2. Load seed data from seed/<Type>/<Type>.json for every type, and load data/SensorReading.csv into
   SensorReading (timestamp, sensorId, value). Show me row counts per type.
3. Make src/app/BadgerTwin.py import the vendored library in src/py/badgertwin (add it to the Python
   runtime path or package it as this platform requires; it needs pandas, numpy, scipy, networkx).
   Fix only _fetch_all()/_dataset() if the fetch API differs. Then run BadgerTwin.detectorTest()
   and show me the result. Expected: first_alert_at 2026-06-08 13:00, warning_hours 217,
   false_alarms 0, glitch_rejected true.
4. Implement the state-changing methods (openIncident, approveWorkOrder, savePlan, approvePlan,
   approveAlert, resetDemo) on the app entities, following src/py/badgertwin/../store.py semantics:
   named approver required, plan needs BOTH "FP&M director" and "VC for Finance", alert needs an
   approved plan, every action writes AuditLog.
5. Build the UI from ui/react-src (React + Tailwind + shadcn/ui + MapLibre). Keep the components;
   only swap src/lib/api.ts so each call hits the matching BadgerTwin method instead of /api/...
   Keep the copy, layout, colors (grey/amber/red mean risk only) and the simulated-data footer.
```

## Map of local API → C3 method

| Local (`badgertwin/server.py`) | C3 (`BadgerTwin` type) |
|---|---|
| `GET /api/state?t=` | `detectLeak(asOf)` + `healthScores(asOf)` + `makeupSeries(start, end)` |
| `GET /api/detector-test` | `detectorTest()` |
| `POST /api/plan` | `planEmergency(spec)` / `savePlan(incidentId, spec)` |
| `GET /api/repairs?budget_usd=` | `rankRepairs(budgetUsd)` |
| `POST /api/ask` | `ask(question, asOf)` |
| `POST /api/incidents` | `openIncident(asOf)` |
| `POST /api/work-orders/{id}/approve` | `approveWorkOrder(id, approver, edits)` |
| `POST /api/plans/{id}/approve` | `approvePlan(id, approvers)` |
| `POST /api/alerts/{id}/approve` | `approveAlert(id, approver, body)` |
| `POST /api/reset` | `resetDemo()` |

## If C3 can't run scipy

The planner falls back automatically to the greedy rule, and the UI shows "solver: greedy". Everything else needs only pandas, numpy and networkx.

## Regenerate the package after changes

```bash
.venv/bin/python scripts/export_c3_package.py
```

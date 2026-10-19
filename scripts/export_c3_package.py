"""Generate the C3 package (c3/badgerTwin) from the dataset and the badgertwin core.

Produces:
  c3/badgerTwin/badgerTwin.c3pkg.json         package manifest
  c3/badgerTwin/src/entity/*.c3typ            one entity Type per CSV (fields = CSV columns, camelCase)
  c3/badgerTwin/src/app/*.c3typ               app-written entities (Incident, EmergencyPlan, ...) + BadgerTwin API type
  c3/badgerTwin/src/app/BadgerTwin.py         Python implementations calling the core
  c3/badgerTwin/src/py/badgertwin/            vendored copy of the core library
  c3/badgerTwin/seed/<Type>/<Type>.json       seed data for every small table
  c3/badgerTwin/data/SensorReading.csv        large timeseries, load once (see C3_IMPORT.md)

Re-run after changing data or core:  .venv/bin/python scripts/export_c3_package.py
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIM, CUR = ROOT / "data" / "simulated", ROOT / "data" / "curated"
PKG = ROOT / "c3" / "badgerTwin"

# Type name -> (csv path, id column, description)
ENTITIES = {
    "Building": (SIM / "buildings.csv", "building_id", "A campus building served by chilled water (public list + estimated loads)."),
    "Plant": (SIM / "plants.csv", "plant_id", "A heating & cooling plant."),
    "Chiller": (SIM / "chillers.csv", "chiller_id", "A plant chiller (capacities partly assumed)."),
    "Pump": (SIM / "pumps.csv", "pump_id", "A distribution pump (simulated)."),
    "NetworkNode": (SIM / "network_nodes.csv", "node_id", "A plant, hub or building node of the simplified network."),
    "PipeSegment": (SIM / "pipe_segments.csv", "pipe_id", "A chilled-water pipe segment. Routes are approximate."),
    "Valve": (SIM / "valves.csv", "valve_id", "An isolation valve on a pipe segment (simulated)."),
    "Sensor": (SIM / "sensors.csv", "sensor_id", "A simulated sensor; readings are in SensorReading."),
    "WeatherHour": (SIM / "weather_demand_hourly.csv", None, "Real Madison weather + modelled campus load factor."),
    "WorkOrder": (SIM / "work_orders.csv", "work_order_id", "Maintenance history (simulated, plus the real 1980 and 2026 events)."),
    "TempChillerSite": (SIM / "temp_chiller_sites.csv", "site_id", "Candidate site for a rented chiller (assumed)."),
    "EventLabel": (SIM / "event_labels.csv", "event_id", "Ground truth for scoring the leak detector."),
    "CostAssumption": (SIM / "cost_assumptions.csv", None, "Market-price inputs of the rental cost model."),
    "ResearchDollars": (SIM / "research_dollars_by_dept.csv", None, "Real NIH award totals by department type."),
    "BuildingResearchMap": (SIM / "building_research_map.csv", None, "Assumed building-to-department mapping."),
    "Source": (CUR / "sources.csv", None, "A cited public source."),
    "TimelineEvent": (CUR / "incident_timeline.csv", None, "A dated public fact about past failures."),
    "CostFact": (CUR / "cost_facts.csv", None, "A reported dollar figure with its quote."),
}

APP_TYPES = {
    "Incident": """// Opened by the Monitoring agent when the leak detector alerts.
entity type Incident schema name "BT_INCIDENT" {
  replayTime: string
  kind: string            // leak | burst | capacity
  suspectedPipe: string   // PipeSegment id
  top3: json
  confidence: string
  headline: string
  evidence: json
  diagnosis: string
  status: string          // open | diagnosed | planned | closed
}
""",
    "WorkOrderDraft": """// Drafted by the Work order agent; approved by a named shift supervisor.
entity type WorkOrderDraft schema name "BT_WO_DRAFT" {
  incidentId: string
  assetId: string
  type: string
  priority: string
  crew: string
  parts: string
  valvesToClose: json
  steps: json
  safety: string
  note: string
  status: string          // draft | approved
  approvedBy: string
  approvedAt: datetime
}
""",
    "EmergencyPlan": """// Produced by planEmergency; approved by the FP&M director AND the VC for Finance.
entity type EmergencyPlan schema name "BT_PLAN" {
  incidentId: string
  inputs: json
  solver: string
  plantCapacityTons: double
  eastDemandTons: double
  buildings: json         // per building: served %, open/closed, why
  placements: json        // rented chillers per site
  costUsdPerDay: double
  dieselGalPerDay: double
  co2TPerDay: double
  summary: string
  status: string          // draft | approved
  approvals: json         // {role: {name, at}}
}
""",
    "CampusAlert": """// Drafted by the Campus alerts agent from an approved plan; approved by Communications.
entity type CampusAlert schema name "BT_ALERT" {
  planId: string
  subject: string
  body: string
  status: string
  approvedBy: string
}
""",
    "AuditLog": """// One row per approval or edit. Never deleted except by "Reset demo".
entity type AuditLog schema name "BT_AUDIT" {
  at: datetime
  actor: string
  action: string
  objectId: string
  before: json
  after: json
}
""",
    "SensorReading": """// Hourly simulated readings (long format). Loaded from data/SensorReading.csv.
// If your platform version prefers timeseries types, convert to TimeseriesHeader/IntervalDataPoint
// (see the playbook, section 2.3); the BadgerTwin methods only need (timestamp, sensorId, value).
entity type SensorReading schema name "BT_SENSOR_READING" {
  timestamp: datetime
  sensorId: string
  value: double
}
""",
}

API_TYPE = """/**
 * BadgerTwin app API. Each method wraps a function of the badgertwin core (src/py/badgertwin).
 * Agents in the C3 Agent Gallery should call THESE methods as tools and must only state numbers
 * the tools return. Anything that changes state requires a named approver (enforced in Python).
 *
 * NOTE: the runtime tag below follows the platform 8.9 docs pattern (`js-server`). If C3 Code
 * reports a different Python runtime name for your version, change `py-server` everywhere here.
 */
type BadgerTwin {
  /** Leak status at a replay hour: kind, headline, top-3 suspect pipes, evidence. */
  detectLeak: function(asOf: string): json py-server

  /** Run the detector hour by hour and score it against EventLabel. */
  detectorTest: function(): json py-server

  /** Make-up water (gal/day, 24-h rolling) between two times, for the Campus chart. */
  makeupSeries: function(start: string, end: string): json py-server

  /** Health risk (Normal / Watch / Act) for every pipe, chiller and pump. */
  healthScores: function(asOf: string): json py-server

  /** Emergency cooling plan. spec: {start, forecastMaxF, extraOutageTons, budgetUsdPerDay, solver}. */
  planEmergency: function(spec: json): json py-server

  /** Ranked pipe replacements within a budget + a drafted Regents request. */
  rankRepairs: function(budgetUsd: double): json py-server

  /** Read-only Q&A with citations. */
  ask: function(question: string, asOf: string): json py-server

  // ---- state-changing actions (each writes AuditLog) ----
  openIncident: function(asOf: string): json py-server
  approveWorkOrder: function(workOrderId: string, approver: string, edits: json): json py-server
  savePlan: function(incidentId: string, spec: json): json py-server
  approvePlan: function(planId: string, approvers: json): json py-server
  approveAlert: function(alertId: string, approver: string, body: string): json py-server
  resetDemo: function(): json py-server
}
"""


def camel(name: str) -> str:
    parts = re.split(r"[_\W]+", name.strip())
    out = parts[0].lower() + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return "id_" if out == "id" else out


def c3_type(series: pd.Series) -> str:
    s = series.dropna()
    if s.empty:
        return "string"
    if pd.api.types.is_bool_dtype(s) or set(s.astype(str).str.lower()) <= {"true", "false"}:
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_float_dtype(s):
        return "double"
    if s.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$").all():
        return "datetime"
    return "string"


def entity_typ(name: str, df: pd.DataFrame, desc: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
    lines = [f"// {desc}", f"// Generated by scripts/export_c3_package.py from the BadgerTwin dataset.",
             f'entity type {name} schema name "BT_{snake}" {{']
    for col in df.columns:
        lines.append(f"  {camel(col)}: {c3_type(df[col])}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def records(df: pd.DataFrame, id_col: str | None, name: str) -> list[dict]:
    out = []
    for i, row in enumerate(df.to_dict("records")):
        rec = {camel(k): (None if pd.isna(v) else v) for k, v in row.items()}
        rec["id"] = str(row[id_col]) if id_col else f"{name}-{i + 1:04d}"
        out.append({k: v for k, v in rec.items() if v is not None})
    return out


PY_IMPL = '''"""Python implementations of the BadgerTwin type. Thin wrappers around the vendored core.

The ONLY platform-specific part is `_dataset()`, which builds the core Dataset from C3 entities.
If a fetch call differs on your platform version, fix it here and nothing else changes.
"""
from __future__ import annotations

import functools

import pandas as pd

from badgertwin import agents
from badgertwin.data import Dataset
from badgertwin.health import health_scores
from badgertwin.leak import LeakDetector
from badgertwin.planner import PlanInputs, plan_emergency
from badgertwin.repairs import rank_repairs

# entity type -> (core attribute, snake_case columns expected by the core)
TABLES = {
    "Building": "buildings", "Plant": "plants", "Chiller": "chillers", "Pump": "pumps",
    "NetworkNode": "nodes", "PipeSegment": "pipes", "Valve": "valves", "Sensor": "sensors",
    "WeatherHour": "weather", "WorkOrder": "work_orders", "TempChillerSite": "sites",
    "EventLabel": "events", "CostAssumption": "cost_assumptions", "BuildingResearchMap": "research_map",
    "Source": "sources", "TimelineEvent": "timeline", "CostFact": "cost_facts",
}


def _snake(name: str) -> str:
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _fetch_all(type_name: str) -> pd.DataFrame:
    """Fetch every row of a C3 entity type as a DataFrame with snake_case columns."""
    t = getattr(c3, type_name)  # noqa: F821  (`c3` is injected by the C3 Python runtime)
    rows, offset = [], 0
    while True:
        batch = t.fetch({"limit": 2000, "offset": offset}).objs or []
        rows += [o.toJson() for o in batch]
        if len(batch) < 2000:
            break
        offset += 2000
    df = pd.DataFrame(rows).drop(columns=["id", "meta", "type", "version"], errors="ignore")
    return df.rename(columns={c: _snake(c) for c in df.columns})


@functools.lru_cache(maxsize=1)
def _dataset() -> Dataset:
    frames = {attr: _fetch_all(t) for t, attr in TABLES.items()}
    readings = _fetch_all("SensorReading")
    for df, cols in ((readings, ["timestamp"]), (frames["weather"], ["timestamp"]),
                     (frames["work_orders"], ["opened", "closed"]), (frames["events"], ["start", "end"])):
        for c in cols:
            df[c] = pd.to_datetime(df[c], format="mixed")
    return Dataset(readings=readings[["timestamp", "sensor_id", "value"]], cost_summary=pd.DataFrame(), **frames)


@functools.lru_cache(maxsize=1)
def _detector() -> LeakDetector:
    return LeakDetector(_dataset())


def detectLeak(cls, asOf):
    return _detector().at(asOf).to_dict()


def makeupSeries(cls, start, end):
    return _detector().makeup_series(start, end).to_dict("records")


def detectorTest(cls):
    return _detector().scan()


def healthScores(cls, asOf):
    return health_scores(_dataset(), as_of=asOf).to_dict("records")


def planEmergency(cls, spec):
    spec = spec or {}
    inp = PlanInputs(start=spec.get("start", "2026-06-17 20:00"), forecast_max_f=spec.get("forecastMaxF"),
                     extra_outage_tons=float(spec.get("extraOutageTons", 0)),
                     budget_usd_per_day=spec.get("budgetUsdPerDay"), solver=spec.get("solver", "auto"))
    return plan_emergency(_dataset(), inp).to_dict()


def rankRepairs(cls, budgetUsd):
    r = rank_repairs(_dataset(), float(budgetUsd or 15e6), as_of="2026-06-01")
    r["request"] = agents.draft_regents_request(r)
    return r


def ask(cls, question, asOf):
    return agents.answer_question(_dataset(), question, as_of=asOf)


# ---- state-changing actions ---------------------------------------------------------------
# These mirror badgertwin/store.py but persist to C3 entities (Incident, WorkOrderDraft,
# EmergencyPlan, CampusAlert, AuditLog). Ask C3 Code to implement them with `merge`/`create`
# following store.py exactly: every approval needs a non-empty name and writes an AuditLog row;
# a plan needs BOTH "FP&M director" and "VC for Finance"; an alert needs an approved plan.
'''


def main() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    (PKG / "src" / "entity").mkdir(parents=True)
    (PKG / "src" / "app").mkdir(parents=True)
    (PKG / "seed").mkdir()
    (PKG / "data").mkdir()

    (PKG / "badgerTwin.c3pkg.json").write_text(json.dumps(
        {"name": "badgerTwin", "version": "1.0.0", "description": "LoopWatch: campus chilled-water digital twin (simulated data)",
         "dependencies": {}}, indent=2) + "\n")

    for name, (path, id_col, desc) in ENTITIES.items():
        df = pd.read_csv(path)
        (PKG / "src" / "entity" / f"{name}.c3typ").write_text(entity_typ(name, df, desc))
        seed_dir = PKG / "seed" / name
        seed_dir.mkdir()
        (seed_dir / f"{name}.json").write_text(json.dumps(records(df, id_col, name), indent=1, default=str))

    for name, body in APP_TYPES.items():
        (PKG / "src" / "app" / f"{name}.c3typ").write_text(body)
    (PKG / "src" / "app" / "BadgerTwin.c3typ").write_text(API_TYPE)
    (PKG / "src" / "app" / "BadgerTwin.py").write_text(PY_IMPL)

    shutil.copytree(ROOT / "badgertwin", PKG / "src" / "py" / "badgertwin",
                    ignore=shutil.ignore_patterns("__pycache__", "server.py", "store.py", "web"))
    shutil.copytree(ROOT / "badgertwin" / "web", PKG / "ui" / "reference-web")
    shutil.copytree(ROOT / "ui" / "src", PKG / "ui" / "react-src")  # the real UI (React + shadcn/ui)

    rd = pd.read_csv(SIM / "sensor_readings_hourly.csv").dropna(subset=["value"])
    rd.rename(columns={"sensor_id": "sensorId"}).to_csv(PKG / "data" / "SensorReading.csv", index=False)

    n_seed = sum(len(json.loads(p.read_text())) for p in (PKG / "seed").rglob("*.json"))
    print(f"wrote {PKG}  ({len(ENTITIES)} entity types, {len(APP_TYPES) + 1} app types, {n_seed} seed rows, "
          f"{len(rd):,} sensor readings)")


if __name__ == "__main__":
    main()

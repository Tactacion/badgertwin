"""Python implementations of the BadgerTwin type. Thin wrappers around the vendored core.

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

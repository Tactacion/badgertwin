"""Local API + web UI for BadgerTwin.  Run:  .venv/bin/uvicorn badgertwin.server:app --reload"""
from __future__ import annotations

import os
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agents
from .geo import buildings_geojson, network_geojson
from .data import (BURST_TIME, ISOLATED_TIME, REPLAY_END, REPLAY_START, SIMULATED_LABEL, Dataset, load_dataset)
from .health import health_scores
from .leak import LeakDetector
from .planner import PlanInputs, plan_emergency
from .repairs import rank_repairs
from .store import PLAN_APPROVER_ROLES, ApprovalError, Store

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
STATE = Path(os.environ.get("BADGERTWIN_STATE", ROOT / "state" / "state.json"))

app = FastAPI(title="BadgerTwin", version="1.0")


@lru_cache(maxsize=1)
def ds() -> Dataset:
    return load_dataset(os.environ.get("BADGERTWIN_DATA", ROOT / "data"))


@lru_cache(maxsize=1)
def detector() -> LeakDetector:
    return LeakDetector(ds())


@lru_cache(maxsize=1)
def store() -> Store:
    return Store(STATE)


def clean(obj):
    """Make numpy/pandas values JSON-safe (NaN → None)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    return obj


def _t(t: str | None) -> pd.Timestamp:
    ts = pd.Timestamp(t or "2026-06-09 08:00").floor("h")
    return min(max(ts, REPLAY_START + pd.Timedelta(hours=24)), REPLAY_END)


# ---------------------------------------------------------------- static network
@app.get("/api/meta")
def meta():
    d = ds()
    return clean(dict(label=SIMULATED_LABEL, replay_start=str(REPLAY_START), replay_end=str(REPLAY_END),
                      burst=str(BURST_TIME), isolated=str(ISOLATED_TIME), approver_roles=PLAN_APPROVER_ROLES,
                      counts={k: len(getattr(d, k)) for k in ("buildings", "plants", "chillers", "pumps", "nodes", "pipes",
                                                              "valves", "sensors", "readings", "weather", "work_orders",
                                                              "sites", "events")}))


@app.get("/api/network")
def network():
    d = ds()
    return clean(dict(nodes=d.nodes.to_dict("records"), pipes=d.pipes.to_dict("records"),
                      buildings=d.buildings.to_dict("records"), plants=d.plants.to_dict("records"),
                      sites=d.sites.to_dict("records")))


@app.get("/api/geo")
def geo():
    d = ds()
    return clean(dict(buildings=buildings_geojson(d, Path(os.environ.get("BADGERTWIN_DATA", ROOT / "data"))),
                      **network_geojson(d)))


# ---------------------------------------------------------------- replay state
@app.get("/api/state")
def state(t: str | None = None):
    """Everything the Campus screen needs at one replay hour."""
    d, det = ds(), detector()
    now = _t(t)
    status = det.at(now)
    w = d.wide.loc[:now].tail(6).mean()  # smooth the last 6 hours
    risk = health_scores(d, as_of=now).set_index("asset_id")
    lead = status.top3[0].pipe_id if status.top3 else None
    others = {s.pipe_id for s in status.top3[1:]}
    flows = pipe_flows(d, w, closed={"CW-M01"} if status.kind == "isolated" else set())
    pipes = []
    for p in d.pipes.itertuples():
        lbl = "Normal"  # live colors show the incident only; long-term health is in `health`
        if status.kind in ("leak", "burst"):
            if p.pipe_id == lead:
                lbl = "Act"
            elif p.pipe_id in others:
                lbl = "Watch"
        if status.kind == "isolated" and p.pipe_id == "CW-M01":
            lbl = "Closed"
        pipes.append(dict(pipe_id=p.pipe_id, label=lbl, health=risk.loc[p.pipe_id, "label"],
                          risk=float(risk.loc[p.pipe_id, "risk"]), **flows[p.pipe_id]))
    buildings = []
    for b in d.buildings.itertuples():
        tin = w.get(f"S-TIN-{b.building_id}")
        flow = w.get(f"S-BFLOW-{b.building_id}")
        lbl = "Normal"
        if tin is not None and np.isfinite(tin):
            lbl = "Act" if tin >= b.max_indoor_temp_f - 1 else "Watch" if tin >= 76 else "Normal"
        buildings.append(dict(building_id=b.building_id, label=lbl, indoor_f=tin, flow_gpm=flow))
    lo = now - pd.Timedelta(days=14)
    return clean(dict(t=str(now), leak=status.to_dict(), pipes=pipes, buildings=buildings,
                      makeup=det.makeup_series(max(lo, REPLAY_START), now).to_dict("records"),
                      outdoor_f=float(d.weather.set_index("timestamp").outdoor_temp_f.get(now, np.nan)),
                      open_incidents=[i for i in store().snapshot()["incidents"] if i["status"] != "closed"]))


AUDIT_AGENT = {"Monitoring agent": ("watcher", "Watcher"), "Work order agent": ("dispatcher", "Dispatcher"),
               "Emergency planning agent": ("planner", "Planner"), "Campus alerts agent": ("messenger", "Messenger")}
AUDIT_TEXT = {"open_incident": "Opened a case.", "draft_work_order": "Drafted a repair order.",
              "approve_work_order": "approved the repair order.", "edit_work_order": "edited the repair order.",
              "draft_plan": "Saved a cooling plan for approval.", "approve_plan": "Plan approved by both signers.",
              "draft_alert": "Drafted the campus email.", "approve_alert": "approved the campus email.",
              "edit_alert": "edited the campus email."}


@lru_cache(maxsize=8)
def _feed_plan(start: str) -> dict:
    return clean(plan_emergency(ds(), PlanInputs(start=start)).to_dict())


@app.get("/api/agents")
def agent_feed(t: str | None = None):
    feed = agents.agent_feed(ds(), detector(), _t(t), plan_fn=_feed_plan)
    for a in store().snapshot()["audit"]:  # what agents and people did in this session
        agent, name = AUDIT_AGENT.get(a["actor"], ("person", a["actor"]))
        action = a["action"]
        text = AUDIT_TEXT.get(action.split(" (")[0], action.replace("_", " "))
        if action.startswith("sign_plan ("):
            text = f"signed the plan as {action[11:-1]}."
        feed.append(dict(at=a["at"], agent=agent, name=name, text=text, level="info", live=True))
    return clean(dict(agents=agents.AGENTS, feed=feed))


def pipe_flows(d: Dataset, w: pd.Series, closed: set[str]) -> dict:
    """Flow (gpm), velocity (ft/s) and direction for every pipe at one moment.
    Magnitudes come from the flow meters (trunks) and building meters (laterals). Direction is
    'away from the nearest open plant', found by a breadth-first search over open pipes."""
    import networkx as nx
    g = nx.Graph()
    for p in d.pipes.itertuples():
        if p.pipe_id not in closed:
            g.add_edge(p.from_node, p.to_node)
    depth = nx.multi_source_dijkstra_path_length(g, [n for n in ("P1", "P2", "P3") if n in g]) if len(g) else {}
    out = {}
    for p in d.pipes.itertuples():
        if p.role == "lateral":
            q = w.get(f"S-BFLOW-{p.to_node}", np.nan)
        elif p.pipe_id == "CW-M01":
            q = w.get("S-FLOW-CW-M01a", np.nan)
        else:
            q = w.get(f"S-FLOW-{p.pipe_id}", np.nan)
        q = 0.0 if (p.pipe_id in closed or q is None or not np.isfinite(q)) else max(0.0, float(q))
        v = q / (2.448 * p.diameter_in ** 2)  # ft/s = gpm / (2.448 · d²)
        fwd = depth.get(p.from_node, 1e9) <= depth.get(p.to_node, 1e9)
        out[p.pipe_id] = dict(flow_gpm=round(q, 1), velocity_fps=round(v, 2), forward=bool(fwd))
    return out


@app.get("/api/history/{asset_id}")
def history(asset_id: str, t: str | None = None, days: int = 7):
    """Last few days for one building or pipe, for the detail panel."""
    d = ds()
    now = _t(t)
    w = d.wide.loc[now - pd.Timedelta(days=max(1, min(days, 30))):now]
    def series(sid: str, every: str = "3h"):
        if sid not in w:
            return []
        s = w[sid].resample(every).mean().dropna()
        return [dict(t=str(i)[5:16], v=round(float(v), 2)) for i, v in s.items()]
    if asset_id in set(d.buildings.building_id):
        b = d.building(asset_id)
        lateral = f"CW-L{asset_id[1:]}"
        return clean(dict(kind="building", id=asset_id, name=b["name"], use=b.use, tons=int(b.design_cooling_tons),
                          limit_f=float(b.max_indoor_temp_f), affected=bool(b.affected_2026), status_2026=b.status_2026,
                          patient_care=bool(b.patient_care), animal_research=bool(b.animal_research),
                          pipe=lateral, indoor=series(f"S-TIN-{asset_id}"), flow=series(f"S-BFLOW-{asset_id}")))
    if asset_id in set(d.pipes.pipe_id):
        p = d.pipe(asset_id)
        r = health_scores(d, as_of=now).set_index("asset_id").loc[asset_id]
        sid = "S-FLOW-CW-M01a" if asset_id == "CW-M01" else f"S-FLOW-{asset_id}"
        if p.role == "lateral":
            sid = f"S-BFLOW-{p.to_node}"
        ends = [n for n in (p.from_node, p.to_node) if f"S-PRES-{n}" in w]
        return clean(dict(kind="pipe", id=asset_id, diameter=int(p.diameter_in), install_year=int(p.install_year),
                          material=p.material, depth_ft=float(p.depth_ft), role=p.role, from_node=p.from_node,
                          to_node=p.to_node, risk=float(r.risk), health=r.label, drivers=r.drivers,
                          flow=series(sid), pressure=series(f"S-PRES-{ends[0]}") if ends else []))
    raise HTTPException(404, "Unknown building or pipe")


@app.get("/api/detector-test")
def detector_test():
    return clean(detector().scan())


@app.get("/api/health")
def health(t: str | None = None):
    return clean(health_scores(ds(), as_of=_t(t)).to_dict("records"))


# ---------------------------------------------------------------- incidents
class OpenIncident(BaseModel):
    t: str


@app.post("/api/incidents")
def open_incident(body: OpenIncident):
    d, det = ds(), detector()
    status = det.at(_t(body.t))
    if not status.alert:
        raise HTTPException(409, "No alert at this time, so there is nothing to open.")
    snap = store().snapshot()
    if not agents.should_open_incident(status, snap["incidents"]):
        pipe = status.top3[0].pipe_id if status.top3 else None
        existing = next(i for i in snap["incidents"] if i["status"] != "closed" and i.get("suspected_pipe") == pipe)
        return clean(dict(incident=existing, existing=True))
    diag = agents.diagnose(d, status)
    inc = store().open_incident(str(status.as_of), status.kind, status.top3[0].pipe_id if status.top3 else None,
                                [asdict(s) for s in status.top3], status.confidence, status.headline,
                                status.evidence, diag["text"])
    wo = store().save_work_order_draft(inc["id"], agents.draft_work_order(d, status))
    return clean(dict(incident=inc, work_order=wo, existing=False))


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    s = store().snapshot()
    inc = next((i for i in s["incidents"] if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return clean(dict(incident=inc, work_orders=[w for w in s["work_orders"] if w["incident_id"] == incident_id],
                      plans=[p for p in s["plans"] if p["incident_id"] == incident_id]))


class Approve(BaseModel):
    approver: str
    edits: dict | None = None


@app.post("/api/work-orders/{wo_id}/approve")
def approve_wo(wo_id: str, body: Approve):
    try:
        return clean(store().approve_work_order(wo_id, body.approver, body.edits))
    except ApprovalError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- emergency plan
class PlanRequest(BaseModel):
    start: str = str(ISOLATED_TIME)
    forecast_max_f: float | None = Field(None, ge=40, le=120)
    extra_outage_tons: float = Field(0, ge=0, le=50_000)
    budget_usd_per_day: float | None = Field(None, ge=0, le=10_000_000)
    value_per_weight_usd: float = Field(2000, gt=0, le=1_000_000)
    solver: str = Field("auto", pattern="^(auto|milp|greedy)$")
    incident_id: str | None = None
    save: bool = False


@app.post("/api/plan")
def plan(body: PlanRequest):
    inp = PlanInputs(start=str(_t(body.start)), forecast_max_f=body.forecast_max_f,
                     extra_outage_tons=body.extra_outage_tons, budget_usd_per_day=body.budget_usd_per_day,
                     value_per_weight_usd=body.value_per_weight_usd, solver=body.solver)
    result = clean(plan_emergency(ds(), inp).to_dict())
    if body.save:
        return clean(store().save_plan(body.incident_id, result))
    return result


class PlanApprove(BaseModel):
    approvers: dict


@app.post("/api/plans/{plan_id}/approve")
def approve_plan(plan_id: str, body: PlanApprove):
    try:
        out = store().approve_plan(plan_id, body.approvers)
        if not out["missing"]:
            out["alert"] = store().save_alert_draft(plan_id, agents.draft_campus_alert(out["plan"]))
        return clean(out)
    except ApprovalError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))


class AlertApprove(BaseModel):
    approver: str
    body: str | None = None


@app.post("/api/alerts/{alert_id}/approve")
def approve_alert(alert_id: str, body: AlertApprove):
    try:
        return clean(store().approve_alert(alert_id, body.approver, body.body))
    except ApprovalError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- repairs, Q&A, sources, audit
@app.get("/api/repairs")
def repairs(budget_usd: float = 15e6):
    if not 0 <= budget_usd <= 500e6:
        raise HTTPException(422, "budget_usd must be between 0 and 500,000,000")
    r = rank_repairs(ds(), budget_usd, as_of=REPLAY_START)
    r["request"] = agents.draft_regents_request(r)
    return clean(r)


class Question(BaseModel):
    question: str
    t: str | None = None


@app.post("/api/ask")
def ask(body: Question):
    return clean(agents.answer_question(ds(), body.question, as_of=_t(body.t)))


@app.get("/api/sources")
def sources():
    d = ds()
    return clean(dict(sources=d.sources.fillna("").to_dict("records"),
                      timeline=d.timeline.fillna("").to_dict("records"),
                      cost_facts=d.cost_facts.fillna("").to_dict("records"),
                      assumptions=d.cost_assumptions.to_dict("records")))


@app.get("/api/audit")
def audit():
    s = store().snapshot()
    return clean(dict(audit=s["audit"][::-1], work_orders=s["work_orders"], plans=[
        {k: v for k, v in p.items() if k not in ("buildings", "hourly")} for p in s["plans"]], alerts=s["alerts"]))


@app.post("/api/reset")
def reset():
    if os.environ.get("BADGERTWIN_ALLOW_RESET", "1") != "1":
        raise HTTPException(403, "Reset is disabled on this server.")
    store().reset()
    return {"ok": True}


DIST = Path(__file__).resolve().parent / "web_dist"
app.mount("/static", StaticFiles(directory=WEB), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/")
def index():
    """The React app (ui/, built into web_dist) if built, else the plain HTML version."""
    return FileResponse(DIST / "index.html" if (DIST / "index.html").exists() else WEB / "index.html")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(DIST / "favicon.svg")


@app.get("/classic")
def classic():
    return FileResponse(WEB / "index.html")

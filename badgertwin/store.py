"""App state: incidents, drafts, approvals and the audit log, kept in one JSON file.

Rule enforced here, not in the UI: nothing becomes "approved" without a named person,
and every approval or edit writes an audit row.
"""
from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

EMPTY = {"incidents": [], "work_orders": [], "plans": [], "alerts": [], "audit": []}
PLAN_APPROVER_ROLES = ("FP&M director", "VC for Finance")
EDITABLE_WO_FIELDS = {"type", "priority", "crew", "parts", "valves_to_close", "steps", "safety", "note"}


class ApprovalError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write(copy.deepcopy(EMPTY))

    # -------------------------------------------------------------- io
    def _read(self) -> dict:
        if not self.path.exists():  # deleted while running: start fresh instead of crashing
            self._write(copy.deepcopy(EMPTY))
        return json.loads(self.path.read_text())

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, default=str))
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        with self._lock:
            return self._read()

    def reset(self) -> None:
        with self._lock:
            self._write(copy.deepcopy(EMPTY))

    def _audit(self, state: dict, actor: str, action: str, object_id: str, before=None, after=None) -> None:
        state["audit"].append(dict(id=uuid.uuid4().hex[:8], at=_now(), actor=actor, action=action,
                                   object_id=object_id, before=before, after=after))

    def _find(self, state: dict, kind: str, oid: str) -> dict:
        for item in state[kind]:
            if item["id"] == oid:
                return item
        raise KeyError(f"{kind} {oid} not found")

    @staticmethod
    def _require(name, role: str) -> str:
        if name is not None and not isinstance(name, str):
            raise ApprovalError(f"The {role}'s name must be text.")
        name = (name or "").strip()
        if len(name) < 2:
            raise ApprovalError(f"A named {role} must approve this.")
        return name

    # -------------------------------------------------------------- incidents
    def open_incident(self, replay_time: str, kind: str, suspected_pipe: str | None, top3: list, confidence: str,
                      headline: str, evidence: list, diagnosis: str) -> dict:
        with self._lock:
            s = self._read()
            inc = dict(id="INC-" + uuid.uuid4().hex[:6].upper(), opened_at=_now(), replay_time=replay_time, kind=kind,
                       suspected_pipe=suspected_pipe, top3=top3, confidence=confidence, headline=headline,
                       evidence=evidence, diagnosis=diagnosis, status="open")
            s["incidents"].append(inc)
            self._audit(s, "Monitoring agent", "open_incident", inc["id"], after=dict(kind=kind, pipe=suspected_pipe))
            self._write(s)
            return inc

    # -------------------------------------------------------------- work orders
    def save_work_order_draft(self, incident_id: str, draft: dict) -> dict:
        with self._lock:
            s = self._read()
            wo = dict(id="WO-" + uuid.uuid4().hex[:6].upper(), incident_id=incident_id, created_at=_now(),
                      status="draft", approved_by=None, approved_at=None, **draft)
            s["work_orders"].append(wo)
            self._find(s, "incidents", incident_id)["status"] = "diagnosed"
            self._audit(s, "Work order agent", "draft_work_order", wo["id"])
            self._write(s)
            return wo

    def approve_work_order(self, wo_id: str, approver: str, edits: dict | None = None) -> dict:
        with self._lock:
            s = self._read()
            wo = self._find(s, "work_orders", wo_id)
            name = self._require(approver, "shift supervisor")
            if wo["status"] == "approved":
                raise ApprovalError("Already approved.")
            if edits:
                bad = set(edits) - EDITABLE_WO_FIELDS
                if bad:
                    raise ApprovalError(f"These fields can't be edited: {', '.join(sorted(bad))}.")
                before = {k: wo.get(k) for k in edits}
                wo.update(edits)
                self._audit(s, name, "edit_work_order", wo_id, before=before, after=edits)
            wo.update(status="approved", approved_by=name, approved_at=_now())
            self._audit(s, name, "approve_work_order", wo_id, before="draft", after="approved")
            self._write(s)
            return wo

    # -------------------------------------------------------------- plans + alerts
    def save_plan(self, incident_id: str | None, plan: dict) -> dict:
        with self._lock:
            s = self._read()
            p = dict(id="PLAN-" + uuid.uuid4().hex[:6].upper(), incident_id=incident_id, created_at=_now(),
                     status="draft", approvals={}, **plan)
            s["plans"].append(p)
            if incident_id:
                try:
                    self._find(s, "incidents", incident_id)["status"] = "planned"
                except KeyError:
                    pass
            self._audit(s, "Emergency planning agent", "draft_plan", p["id"], after=dict(cost=plan.get("cost_usd_per_day")))
            self._write(s)
            return p

    def approve_plan(self, plan_id: str, approvers: dict) -> dict:
        """Both roles must sign. Partial signatures are recorded; status flips when both are in."""
        with self._lock:
            s = self._read()
            p = self._find(s, "plans", plan_id)
            if p["status"] == "approved":
                raise ApprovalError("Already approved.")
            for role in PLAN_APPROVER_ROLES:
                if approvers.get(role):
                    name = self._require(approvers[role], role)
                    others = {a["name"].casefold() for r, a in p["approvals"].items() if r != role}
                    if name.casefold() in others:
                        raise ApprovalError("The two approvers must be different people.")
                    p["approvals"][role] = dict(name=name, at=_now())
                    self._audit(s, name, f"sign_plan ({role})", plan_id)
            names = [a["name"].casefold() for a in p["approvals"].values()]
            if len(names) != len(set(names)):
                raise ApprovalError("The two approvers must be different people.")
            missing = [r for r in PLAN_APPROVER_ROLES if r not in p["approvals"]]
            if not missing:
                p["status"] = "approved"
                self._audit(s, " + ".join(a["name"] for a in p["approvals"].values()), "approve_plan", plan_id,
                            before="draft", after="approved")
            self._write(s)
            return dict(plan=p, missing=missing)

    def save_alert_draft(self, plan_id: str, alert: dict) -> dict:
        with self._lock:
            s = self._read()
            plan = self._find(s, "plans", plan_id)
            if plan["status"] != "approved":
                raise ApprovalError("The plan must be approved before a campus alert is drafted.")
            a = dict(id="ALERT-" + uuid.uuid4().hex[:6].upper(), plan_id=plan_id, created_at=_now(),
                     status="draft", approved_by=None, **alert)
            s["alerts"].append(a)
            self._audit(s, "Campus alerts agent", "draft_alert", a["id"])
            self._write(s)
            return a

    def approve_alert(self, alert_id: str, approver: str, body: str | None = None) -> dict:
        with self._lock:
            s = self._read()
            a = self._find(s, "alerts", alert_id)
            name = self._require(approver, "Communications office approver")
            if a["status"] != "draft":
                raise ApprovalError("Already approved.")
            if body and body != a["body"]:
                self._audit(s, name, "edit_alert", alert_id, before=a["body"], after=body)
                a["body"] = body
            a.update(status="approved (not sent: demo)", approved_by=name, approved_at=_now())
            self._audit(s, name, "approve_alert", alert_id, before="draft", after="approved")
            self._write(s)
            return a

"""BadgerTwin tests: each one checks a promise the demo makes to judges."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from badgertwin.data import load_dataset, load_factor
from badgertwin.health import health_scores
from badgertwin.leak import LeakDetector
from badgertwin.planner import CostParams, PlanInputs, plan_emergency
from badgertwin.repairs import _knapsack, rank_repairs
from badgertwin.store import ApprovalError, Store


@pytest.fixture(scope="session")
def ds():
    return load_dataset()


@pytest.fixture(scope="session")
def det(ds):
    return LeakDetector(ds)


@pytest.fixture(scope="session")
def scan(det):
    return det.scan()


# ------------------------------------------------------------------ data
@pytest.mark.unit
def test_dataset_shapes(ds):
    assert len(ds.buildings) == 50 and ds.buildings.affected_2026.sum() == 34
    assert {"P1", "P2", "P3"} == set(ds.plants.plant_id)
    assert "CW-M01" in set(ds.pipes.pipe_id)
    assert (ds.buildings.data_origin.str.len() > 0).all()


@pytest.mark.unit
def test_load_factor_matches_generator(ds):
    w = ds.weather.set_index("timestamp")
    lf = load_factor(w.outdoor_temp_f.to_numpy(), w.index)
    assert np.allclose(lf, w.campus_load_factor.to_numpy(), atol=1e-3)


# ------------------------------------------------------------------ leak detection
@pytest.mark.unit
def test_leak_caught_days_before_burst(scan):
    assert scan["first_alert_at"] is not None
    assert scan["warning_hours"] >= 7 * 24  # pitch promise: 7+ days of warning


@pytest.mark.unit
def test_no_false_alarms_and_glitch_rejected(scan):
    assert scan["false_alarms"] == 0
    assert scan["glitch_rejected"] is True


@pytest.mark.unit
def test_right_pipe_in_top3(scan):
    assert scan["cw_m01_in_top3_at_first"] is True
    assert scan["cw_m01_rank1_three_days_later"] is True


@pytest.mark.unit
def test_states_through_the_replay(det):
    assert det.at("2026-06-05 12:00").kind == "normal"
    assert det.at("2026-06-12 08:00").kind == "leak"
    assert det.at("2026-06-17 15:00").kind == "burst"
    assert det.at("2026-06-20 12:00").kind == "isolated"


# ------------------------------------------------------------------ health
@pytest.mark.unit
def test_health_ranks_old_main_high(ds):
    h = health_scores(ds, as_of="2026-06-01").set_index("asset_id")
    pipes = h[h.asset_type == "pipe"].sort_values("risk", ascending=False)
    assert "CW-M01" in pipes.index[:3]
    assert set(h.label) <= {"Normal", "Watch", "Act"}


@pytest.mark.unit
def test_health_ignores_future_work_orders(ds):
    before = health_scores(ds, as_of="2026-06-01").set_index("asset_id").loc["CW-M01", "risk"]
    after = health_scores(ds, as_of="2026-09-01").set_index("asset_id").loc["CW-M01", "risk"]
    assert after > before  # the 2026 break only counts once it has happened


# ------------------------------------------------------------------ planner
@pytest.fixture(scope="session")
def hot_plan(ds):
    return plan_emergency(ds, PlanInputs(forecast_max_f=95))


@pytest.mark.unit
def test_patient_care_always_served(ds, hot_plan):
    care = set(ds.buildings[ds.buildings.patient_care & ds.buildings.affected_2026].building_id)
    for b in hot_plan.buildings:
        if b["building_id"] in care:
            assert b["status"] == "open" and b["served_pct"] == 100


@pytest.mark.unit
def test_plan_respects_plant_capacity_and_limits(hot_plan):
    # per-building values are rounded to whole tons, so allow 0.5 t of rounding per building
    assert sum(b["plant_tons"] for b in hot_plan.buildings) <= hot_plan.plant_capacity_tons + 0.5 * len(hot_plan.buildings)
    for b in hot_plan.buildings:
        if b["status"] == "open":
            assert b["peak_indoor_f"] <= b["max_indoor_f"] + 0.1


@pytest.mark.unit
def test_rental_tons_fit_rented_units(hot_plan):
    rented = sum(b["rental_tons"] for b in hot_plan.buildings)
    assert rented <= hot_plan.rented_tons + 0.5 * len(hot_plan.buildings)


@pytest.mark.unit
def test_hotter_or_less_capacity_never_cheaper_and_open(ds, hot_plan):
    mild = plan_emergency(ds, PlanInputs(forecast_max_f=80))
    worse = plan_emergency(ds, PlanInputs(forecast_max_f=95, extra_outage_tons=1500))
    score = lambda p: (p.kept_open, -p.cost_usd_per_day)  # noqa: E731
    assert score(mild) >= score(hot_plan) >= score(worse)


@pytest.mark.unit
def test_budget_is_respected(ds):
    p = plan_emergency(ds, PlanInputs(forecast_max_f=95, extra_outage_tons=1500, budget_usd_per_day=15_000))
    assert p.cost_usd_per_day <= 15_000


@pytest.mark.unit
def test_greedy_fallback_is_valid_and_no_better_than_milp(ds, hot_plan):
    g = plan_emergency(ds, PlanInputs(forecast_max_f=95, solver="greedy"))
    assert g.solver == "greedy"
    weight = {b["building_id"]: b["weight"] for b in hot_plan.buildings}
    value = lambda p: sum(weight[b["building_id"]] for b in p.buildings if b["status"] == "open") - p.cost_usd_per_day / 2000  # noqa: E731
    assert value(hot_plan) >= value(g) - 1e-6


@pytest.mark.unit
def test_unit_costs_are_in_market_range():
    u = CostParams().unit(500)
    assert 4_000 < u["usd_per_day"] < 12_000  # ~30 units ≈ $156K–$233K/day in 2026


# ------------------------------------------------------------------ repairs
@pytest.mark.unit
def test_knapsack_optimal_small():
    chosen = _knapsack(np.array([100_000, 200_000, 300_000.0]), np.array([10, 15, 30.0]), 400_000)
    assert chosen.tolist() == [True, False, True]


@pytest.mark.unit
def test_repairs_within_budget(ds):
    r = rank_repairs(ds, 10e6, as_of="2026-06-01")
    assert r["selected_cost_usd"] <= 10e6
    assert r["ranking"][0]["selected"]


# ------------------------------------------------------------------ approvals
@pytest.mark.unit
def test_store_requires_named_approvers(tmp_path):
    s = Store(tmp_path / "s.json")
    inc = s.open_incident("t", "leak", "CW-M01", [], "low", "h", [], "d")
    wo = s.save_work_order_draft(inc["id"], {"type": "x"})
    with pytest.raises(ApprovalError):
        s.approve_work_order(wo["id"], " ")
    plan = s.save_plan(inc["id"], {"cost_usd_per_day": 1, "buildings": []})
    with pytest.raises(ApprovalError):
        s.save_alert_draft(plan["id"], {"body": "x"})  # plan not approved yet
    assert s.approve_plan(plan["id"], {"FP&M director": "A B"})["missing"] == ["VC for Finance"]
    assert s.approve_plan(plan["id"], {"VC for Finance": "C D"})["plan"]["status"] == "approved"
    assert any(a["action"] == "approve_plan" for a in s.snapshot()["audit"])


# ------------------------------------------------------------------ API end to end
@pytest.mark.integration
def test_full_demo_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BADGERTWIN_STATE", str(tmp_path / "state.json"))
    import importlib

    import badgertwin.server as server
    importlib.reload(server)
    c = TestClient(server.app)
    assert c.post("/api/incidents", json={"t": "2026-06-05 12:00"}).status_code == 409
    r = c.post("/api/incidents", json={"t": "2026-06-10 08:00"}).json()
    assert r["incident"]["suspected_pipe"] == "CW-M01" and r["work_order"]["valves_to_close"]
    assert c.post(f"/api/work-orders/{r['work_order']['id']}/approve", json={"approver": ""}).status_code == 400
    assert c.post(f"/api/work-orders/{r['work_order']['id']}/approve", json={"approver": "Pat Lee"}).json()["status"] == "approved"
    p = c.post("/api/plan", json={"forecast_max_f": 95, "save": True, "incident_id": r["incident"]["id"]}).json()
    out = c.post(f"/api/plans/{p['id']}/approve", json={"approvers": {"FP&M director": "A B", "VC for Finance": "C D"}}).json()
    assert out["missing"] == [] and out["alert"]["status"] == "draft"
    assert c.post(f"/api/alerts/{out['alert']['id']}/approve", json={"approver": "E F"}).json()["approved_by"] == "E F"
    ans = c.post("/api/ask", json={"question": "How old is CW-M01?"}).json()
    assert "1966" in ans["answer"] and ans["citations"]
    assert len(c.get("/api/audit").json()["audit"]) >= 6


# ------------------------------------------------------------------ review fixes
@pytest.mark.unit
def test_same_person_cannot_sign_both_roles(tmp_path):
    s = Store(tmp_path / "s.json")
    plan = s.save_plan(None, {"cost_usd_per_day": 1, "buildings": []})
    s.approve_plan(plan["id"], {"FP&M director": "Alex Kim"})
    with pytest.raises(ApprovalError):
        s.approve_plan(plan["id"], {"VC for Finance": "alex kim"})
    with pytest.raises(ApprovalError):
        s.approve_plan(plan["id"], {"VC for Finance": 5})


@pytest.mark.unit
def test_work_order_edit_allow_list_and_alert_once(tmp_path):
    s = Store(tmp_path / "s.json")
    inc = s.open_incident("t", "leak", "CW-M01", [], "low", "h", [], "d")
    wo = s.save_work_order_draft(inc["id"], {"type": "x"})
    with pytest.raises(ApprovalError):
        s.approve_work_order(wo["id"], "Pat Lee", {"id": "hacked"})
    plan = s.save_plan(inc["id"], {"cost_usd_per_day": 1, "buildings": []})
    s.approve_plan(plan["id"], {"FP&M director": "A B", "VC for Finance": "C D"})
    alert = s.save_alert_draft(plan["id"], {"subject": "s", "body": "b"})
    s.approve_alert(alert["id"], "E F")
    with pytest.raises(ApprovalError):
        s.approve_alert(alert["id"], "G H", "changed")


@pytest.mark.unit
def test_planner_capacity_never_uses_future_readings(ds):
    early = plan_emergency(ds, PlanInputs(start="2026-06-10 08:00", forecast_max_f=90))
    at_shutoff = plan_emergency(ds, PlanInputs(forecast_max_f=90))
    assert early.plant_capacity_tons == at_shutoff.plant_capacity_tons == 3_500


@pytest.mark.unit
def test_greedy_patient_care_and_no_wasted_rentals(ds):
    g = plan_emergency(ds, PlanInputs(forecast_max_f=95, solver="greedy"))
    care = set(ds.buildings[ds.buildings.patient_care].building_id)
    assert all(b["status"] == "open" for b in g.buildings if b["building_id"] in care)
    assert all(b["rental_tons"] == 0 for b in g.buildings if b["status"] == "closed")
    assert sum(b["rental_tons"] for b in g.buildings) <= g.rented_tons + 0.5 * len(g.buildings)

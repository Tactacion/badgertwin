"""Tool 5: repair priorities. Expected loss = chance of failure × cost of that failure.

Cost of a failure = cooling lost while it's fixed (tons that can no longer reach buildings, found
by max-flow on the network with the pipe removed, × $/ton-day × criticality × outage days)
+ the emergency repair itself. Then pick the best set of planned replacements for a budget.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from .data import Dataset
from .health import health_scores

# $10M of temporary cooling for ~11,700 tons over ~54 days in 2026 ≈ $16 per ton-day (see README).
USD_PER_TON_DAY = 10_000_000 / (11_691 * 54)
DESIGN_VELOCITY_FPS = 7.0


def _pipe_capacity_tons(diameter_in: float) -> float:
    gpm = 2.448 * diameter_in ** 2 * DESIGN_VELOCITY_FPS
    return gpm / 2.0  # 2 gpm per ton at a 12 °F temperature difference


def _outage_days(diameter_in: float) -> float:
    return 54.0 if diameter_in >= 36 else 21.0 if diameter_in >= 20 else 7.0


def _emergency_repair_usd(p) -> float:
    # Scaled from the 2026 break: ~$1.8M for the 48-in main at 20 ft (+ nearby damage found).
    return 1_800_000 * (p.diameter_in / 48) * (p.depth_ft / 20) ** 0.5


def _planned_replacement_usd(p) -> float:
    # Planned work costs far less per foot than an emergency dig; ~$1,100/ft for 48-in, scaled.
    return 1_100 * (p.diameter_in / 48) ** 1.2 * p.length_ft + 150_000


def _graph(ds: Dataset) -> nx.DiGraph:
    g = nx.DiGraph()
    for p in ds.pipes.itertuples():
        cap = _pipe_capacity_tons(p.diameter_in)
        g.add_edge(p.from_node, p.to_node, capacity=cap, pipe=p.pipe_id)
        g.add_edge(p.to_node, p.from_node, capacity=cap, pipe=p.pipe_id)
    plants = ds.plants.set_index("plant_id").total_capacity_tons
    for pid, cap in plants.items():
        g.add_edge("SRC", pid, capacity=float(cap))
    for b in ds.buildings.itertuples():
        g.add_edge(b.building_id, "SINK", capacity=float(b.design_cooling_tons))
    return g


def _weighted_served(g: nx.DiGraph, weights: dict) -> float:
    _, flow = nx.maximum_flow(g, "SRC", "SINK")
    return sum(flow[b]["SINK"] * weights[b] for b in weights)


MAX_BUDGET_USD = 500e6


def rank_repairs(ds: Dataset, budget_usd: float = 50e6, as_of=None) -> dict:
    budget_usd = float(min(max(budget_usd, 0.0), MAX_BUDGET_USD))
    risk = health_scores(ds, as_of=as_of).set_index("asset_id")
    weights = ds.buildings.set_index("building_id").criticality_weight
    w_norm = (weights / weights.mean()).to_dict()
    g = _graph(ds)
    base = _weighted_served(g, w_norm)
    rows = []
    for p in ds.pipes.itertuples():
        h = g.copy()
        h.remove_edge(p.from_node, p.to_node)
        h.remove_edge(p.to_node, p.from_node)
        lost = max(0.0, base - _weighted_served(h, w_norm))  # criticality-weighted tons
        days = _outage_days(p.diameter_in)
        failure_cost = lost * USD_PER_TON_DAY * days + _emergency_repair_usd(p)
        r = float(risk.loc[p.pipe_id, "risk"])
        rows.append(dict(pipe_id=p.pipe_id, role=p.role, diameter_in=int(p.diameter_in),
                         install_year=int(p.install_year), material=p.material, risk=r,
                         risk_label=risk.loc[p.pipe_id, "label"], weighted_tons_lost=round(lost),
                         outage_days=days, failure_cost_usd=round(failure_cost),
                         expected_loss_usd=round(r * failure_cost),
                         replacement_cost_usd=round(_planned_replacement_usd(p)),
                         drivers=risk.loc[p.pipe_id, "drivers"]))
    df = pd.DataFrame(rows)
    # Replacing a pipe removes most (assume 90%) of its expected loss.
    df["benefit_usd"] = (0.9 * df.expected_loss_usd).round()
    df["benefit_per_dollar"] = (df.benefit_usd / df.replacement_cost_usd).round(3)
    chosen = _knapsack(df.replacement_cost_usd.to_numpy(), df.benefit_usd.to_numpy(), budget_usd)
    df["selected"] = chosen
    df = df.sort_values(["selected", "expected_loss_usd"], ascending=[False, False]).reset_index(drop=True)
    sel = df[df.selected]
    return dict(budget_usd=budget_usd, selected_cost_usd=int(sel.replacement_cost_usd.sum()),
                selected_benefit_usd=int(sel.benefit_usd.sum()), n_selected=int(len(sel)),
                usd_per_ton_day=round(USD_PER_TON_DAY, 2), ranking=df.to_dict("records"))


def _knapsack(cost: np.ndarray, value: np.ndarray, budget: float, step: float = 50_000) -> np.ndarray:
    """0/1 knapsack by dynamic programming on $50K steps (68 pipes: instant)."""
    c = np.ceil(cost / step).astype(int)
    cap = int(budget // step)
    n = len(c)
    best = np.zeros(cap + 1)
    keep = np.zeros((n, cap + 1), dtype=bool)
    for i in range(n):
        if c[i] > cap:
            continue
        cand = best[: cap + 1 - c[i]] + value[i]
        better = cand > best[c[i]:]
        keep[i, c[i]:] = better
        best[c[i]:] = np.where(better, cand, best[c[i]:])
    chosen = np.zeros(n, dtype=bool)
    k = cap
    for i in range(n - 1, -1, -1):
        if keep[i, k]:
            chosen[i] = True
            k -= c[i]
    return chosen

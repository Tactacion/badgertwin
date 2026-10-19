"""Tool 2: equipment health. A transparent hazard model, not a black box.

risk = 1 - exp(-λ) is read as "chance of a failure in the next 10 years".
λ multiplies simple, explainable factors so the UI can say WHY an asset ranks high.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Dataset

MATERIAL_BASE = {"concrete-coated steel": 0.25, "steel": 0.20, "ductile iron": 0.12, "HDPE": 0.06}
SOIL = {"silty clay": 1.2, "sandy fill": 1.0, "glacial till": 0.9}
WATCH, ACT = 0.25, 0.5
NOW_YEAR = 2026


def risk_label(risk: float) -> str:
    return "Act" if risk >= ACT else "Watch" if risk >= WATCH else "Normal"


def _emergency_counts(ds: Dataset, as_of) -> pd.Series:
    wo = ds.work_orders
    if as_of is not None:
        wo = wo[wo.opened < pd.Timestamp(as_of)]
    return wo[wo.priority == "emergency"].groupby("asset_id").size()


def health_scores(ds: Dataset, as_of=None) -> pd.DataFrame:
    """One row per pipe, chiller and pump: risk 0-1, a plain label and the drivers behind it."""
    emerg = _emergency_counts(ds, as_of)
    rows = []
    for p in ds.pipes.itertuples():
        age = NOW_YEAR - p.install_year
        f_age = (age / 50) ** 2
        f_depth = 1 + (p.depth_ft - 10) / 20
        f_soil = SOIL.get(p.soil, 1.0)
        f_tunnel = 0.6 if p.in_tunnel else 1.0
        n_em = int(emerg.get(p.pipe_id, 0))
        lam = MATERIAL_BASE.get(p.material, 0.15) * f_age * f_depth * f_soil * f_tunnel * (1 + 0.5 * n_em)
        drivers = [f"{age} years old", p.material, f"{p.depth_ft:g} ft deep", p.soil]
        if p.in_tunnel:
            drivers.append("in a walkable tunnel (easier to inspect)")
        if n_em:
            drivers.append(f"{n_em} past emergency repair(s)")
        rows.append(dict(asset_id=p.pipe_id, asset_type="pipe", lam=lam, drivers="; ".join(drivers)))
    for c in ds.chillers.itertuples():
        age = NOW_YEAR - c.install_year
        drift = max(0.0, c.current_kw_per_ton / c.design_kw_per_ton - 1)
        n_em = int(emerg.get(c.chiller_id, 0))
        lam = 0.04 * (age / 20) ** 2 + 1.5 * drift ** 2 + 0.2 * n_em
        drivers = [f"{age} years old", f"uses {drift:.0%} more power per ton than design"]
        if n_em:
            drivers.append(f"{n_em} past emergency repair(s)")
        rows.append(dict(asset_id=c.chiller_id, asset_type="chiller", lam=lam, drivers="; ".join(drivers)))
    for m in ds.pumps.itertuples():
        age = NOW_YEAR - m.install_year
        n_em = int(emerg.get(m.pump_id, 0))
        lam = 0.05 * (age / 20) ** 2 + 0.2 * n_em
        drivers = [f"{age} years old"] + ([f"{n_em} past emergency repair(s)"] if n_em else [])
        rows.append(dict(asset_id=m.pump_id, asset_type="pump", lam=lam, drivers="; ".join(drivers)))
    df = pd.DataFrame(rows)
    df["risk"] = (1 - np.exp(-df.lam)).round(3)
    df["label"] = df.risk.map(risk_label)
    return df.drop(columns="lam").sort_values("risk", ascending=False).reset_index(drop=True)

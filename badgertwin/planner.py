"""Tool 3: emergency cooling plan.

When the Charter main is valved off, the east zone (the 34 buildings hit in 2026) can only get
plant water through two small crossovers. The planner decides, for the peak hour of the next
72 hours:
  * how many tons of plant water each east-zone building gets,
  * how many rented chillers (300/400/500 tons) go to which candidate site, and which buildings
    each site feeds (only buildings within SERVE_RADIUS_M),
  * which buildings close because they can't be kept below their safe indoor temperature,
maximising "value of buildings kept open" minus the daily rental bill. Patient-care buildings are
always fully served. It then replays the 72 hours with that allocation to report peak indoor temps.

Solved as a mixed-integer program with scipy's HiGHS (scipy.optimize.milp). If that is unavailable
or fails, a greedy rule produces a valid plan so the demo never breaks.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .data import ISOLATED_TIME, Dataset, load_factor

UNIT_SIZES = (300, 400, 500)
SERVE_RADIUS_M = 150.0
INDOOR_RISE_AT_DESIGN_F = 22.0  # °F indoor rise if a building gets 0% at full design load
BASE_INDOOR_F = 72.0
DEFAULT_VALUE_PER_WEIGHT_USD = 2_000.0  # $/day the university would pay to keep 1 weight-point open
UW_ACTUAL_USD_PER_DAY = (156_000, 233_000)
# Plant water that can reach the east zone through the two 8-in crossovers once CW-M01 is shut,
# from the hydraulic model (median delivered flow ÷ 2 gpm/ton). Used until real readings exist.
RATED_EAST_CAPACITY_TONS = 3_500.0


@dataclass(frozen=True)
class CostParams:
    """Daily cost per rented unit, from market prices (see data/simulated/cost_assumptions.csv)."""
    rent_usd_per_week_500t: float = 8_666.0
    emergency_multiplier: float = 1.2
    kw_per_ton: float = 1.10
    avg_load: float = 0.70
    diesel_usd_per_gal: float = 4.96  # US average, Jul 2026 (FRED GASDESW)
    setup_usd_per_unit: float = 45_000.0
    expected_days: float = 54.0  # 2026 outage length
    co2_kg_per_gal: float = 10.21

    def unit(self, tons: int) -> dict:
        gen_kw = tons * self.kw_per_ton * 1.15
        rent = self.rent_usd_per_week_500t * (tons / 500) * self.emergency_multiplier / 7
        gen_rent = float(np.interp(gen_kw, [750, 1000], [4800, 5640])) * 2 / 7  # 24/7 = two shifts
        gal_h = float(np.interp(self.avg_load, [0.5, 0.75, 1.0], [27.4, 39.3, 51.0])) * gen_kw / 750
        diesel = gal_h * 24
        setup = self.setup_usd_per_unit / self.expected_days
        return dict(tons=tons, usd_per_day=rent + gen_rent + diesel * self.diesel_usd_per_gal + setup,
                    diesel_gal_per_day=diesel, co2_t_per_day=diesel * self.co2_kg_per_gal / 1000)


@dataclass(frozen=True)
class PlanInputs:
    start: str = str(ISOLATED_TIME)
    horizon_h: int = 72
    forecast_max_f: float | None = None  # None = use the real forecast (weather data)
    extra_outage_tons: float = 0.0  # e.g. a judge knocks out a chiller
    budget_usd_per_day: float | None = None
    value_per_weight_usd: float = DEFAULT_VALUE_PER_WEIGHT_USD
    safety_margin_f: float = 2.0  # keep open buildings this many °F under their limit
    plant_capacity_tons: float | None = None  # None = measured crossover flow ÷ 2 gpm/ton
    solver: str = "auto"  # "auto" | "milp" | "greedy"


@dataclass
class Plan:
    inputs: dict
    solver: str
    solve_ms: float
    solve_status: str
    plant_capacity_tons: float
    peak_hour: str
    peak_outdoor_f: float
    east_demand_tons: float
    buildings: list[dict]
    placements: list[dict]
    cost_usd_per_day: float
    diesel_gal_per_day: float
    co2_t_per_day: float
    rented_units: int
    rented_tons: int
    kept_open: int
    closed: int
    uw_actual_usd_per_day: tuple = UW_ACTUAL_USD_PER_DAY
    summary: str = ""
    hourly: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _horizon(ds: Dataset, inp: PlanInputs) -> pd.DataFrame:
    """Outdoor temps and load factor for the horizon; optionally rescaled to a forecast max."""
    wx = ds.weather.set_index("timestamp")
    t0 = pd.Timestamp(inp.start).floor("h")
    h = wx.loc[t0:t0 + pd.Timedelta(hours=inp.horizon_h - 1), ["outdoor_temp_f"]].copy()
    if inp.forecast_max_f is not None:
        # Shift so the daily highs reach the forecast while nights stay realistic.
        lo, hi = h.outdoor_temp_f.min(), h.outdoor_temp_f.max()
        span = max(hi - lo, 1.0)
        new_lo = min(lo + (inp.forecast_max_f - hi) * 0.6, inp.forecast_max_f - 5)
        h["outdoor_temp_f"] = new_lo + (h.outdoor_temp_f - lo) / span * (inp.forecast_max_f - new_lo)
    h["load_factor"] = load_factor(h.outdoor_temp_f.to_numpy(), h.index)
    return h


def _east_capacity(ds: Dataset, inp: PlanInputs, hz: pd.DataFrame) -> float:
    """Never looks past the plan start: uses the last 24 h of crossover readings once the main has
    been shut for 6+ hours, otherwise the rated value from the hydraulic model."""
    t0 = hz.index[0]
    cap = RATED_EAST_CAPACITY_TONS
    if inp.plant_capacity_tons is not None:
        cap = inp.plant_capacity_tons
    elif t0 >= ISOLATED_TIME + pd.Timedelta(hours=6):
        w = ds.wide.loc[max(ISOLATED_TIME + pd.Timedelta(hours=1), t0 - pd.Timedelta(hours=23)):t0]
        cols = [c for c in w.columns if c.startswith("S-FLOW-CW-X")]
        if cols and len(w):
            cap = float(w[cols].sum(axis=1).median() / 2.0)
    return max(0.0, cap - inp.extra_outage_tons)


def _problem(ds: Dataset, inp: PlanInputs):
    hz = _horizon(ds, inp)
    peak_t = hz.load_factor.idxmax()
    lf_peak = float(hz.load_factor.max())
    east = ds.buildings[ds.buildings.affected_2026].reset_index(drop=True).copy()
    east["peak_tons"] = east.design_cooling_tons * lf_peak
    # Smallest served share that keeps indoor temp under the limit at the peak hour.
    allowed_rise = (east.max_indoor_temp_f - inp.safety_margin_f - BASE_INDOOR_F).clip(lower=0)
    east["min_share"] = (1 - allowed_rise / (INDOOR_RISE_AT_DESIGN_F * lf_peak)).clip(0, 1)
    east.loc[east.patient_care, "min_share"] = 1.0
    sites = ds.sites.reset_index(drop=True)
    reach = [[_haversine_m(s.lat, s.lon, b.lat, b.lon) <= SERVE_RADIUS_M for b in east.itertuples()]
             for s in sites.itertuples()]
    return hz, peak_t, lf_peak, east, sites, np.array(reach, dtype=bool)


def _solve_milp(east, sites, reach, cap, units, inp):
    from scipy.optimize import Bounds, LinearConstraint, milp

    nb, ns, nu = len(east), len(sites), len(UNIT_SIZES)
    pairs = [(s, b) for s in range(ns) for b in range(nb) if reach[s, b]]
    # Variable layout: p[b] plant tons | r[pair] rental tons | n[s,u] units (int) | o[b] open (bin)
    ip, ir = 0, nb
    inn = ir + len(pairs)
    io = inn + ns * nu
    nv = io + nb
    c = np.zeros(nv)
    lam = 1.0 / inp.value_per_weight_usd
    for s in range(ns):
        for u, sz in enumerate(UNIT_SIZES):
            c[inn + s * nu + u] = lam * units[sz]["usd_per_day"]
    for b, row in east.iterrows():
        c[io + b] = -float(row.criticality_weight)
        c[ip + b] = -1e-6  # tiny nudge: prefer serving more when free
    A, lo, hi = [], [], []

    def add(coeffs: dict, lb, ub):
        row = np.zeros(nv)
        for k, v in coeffs.items():
            row[k] += v
        A.append(row), lo.append(lb), hi.append(ub)

    add({ip + b: 1.0 for b in range(nb)}, -np.inf, cap)  # plant capacity to the east zone
    for b, row in east.iterrows():
        served = {ip + b: 1.0} | {ir + k: 1.0 for k, (s, bb) in enumerate(pairs) if bb == b}
        add(served, -np.inf, float(row.peak_tons))  # never more than the building needs
        need = float(row.min_share * row.peak_tons)
        add(served | {io + b: -need}, 0.0, np.inf)  # open ⇒ served ≥ min share
    for s, srow in sites.iterrows():
        k_s = {ir + k: 1.0 for k, (ss, _) in enumerate(pairs) if ss == s}
        add(k_s | {inn + s * nu + u: -float(sz) for u, sz in enumerate(UNIT_SIZES)}, -np.inf, 0.0)
        add({inn + s * nu + u: 1.0 for u in range(nu)}, 0, int(srow.max_units))
    if inp.budget_usd_per_day is not None:
        add({inn + s * nu + u: units[sz]["usd_per_day"] for s in range(ns) for u, sz in enumerate(UNIT_SIZES)},
            -np.inf, inp.budget_usd_per_day)

    lb, ub = np.zeros(nv), np.full(nv, np.inf)
    ub[inn:io] = 3
    ub[io:] = 1
    for b, row in east.iterrows():
        if row.patient_care:
            lb[io + b] = 1  # patient care must stay open
    integrality = np.zeros(nv)
    integrality[inn:] = 1
    res = milp(c, constraints=LinearConstraint(np.array(A), lo, hi), integrality=integrality,
               bounds=Bounds(lb, ub), options={"time_limit": 10, "mip_rel_gap": 1e-4})
    if res.x is None:
        raise RuntimeError(res.message)
    x = res.x
    plant = x[ip:ir]
    rent = np.zeros(nb)
    site_feeds = {s: [] for s in range(ns)}
    for k, (s, b) in enumerate(pairs):
        if x[ir + k] > 1e-6:
            rent[b] += x[ir + k]
            site_feeds[s].append((b, x[ir + k]))
    n = np.rint(x[inn:io]).reshape(ns, nu).astype(int)
    is_open = np.rint(x[io:]).astype(bool)
    return plant, rent, n, is_open, site_feeds, "milp (HiGHS)"


def _solve_greedy(east, sites, reach, cap, units, inp):
    """Simple rule for comparison and as a fallback. Priority order: patient care, then weight per ton.
    Each building first gets just enough (its minimum share) from plant water, then from rentals
    if a unit is worth it; if it still can't stay open, everything given to it is taken back.
    Leftover plant water then tops up open buildings."""
    nb, ns, nu = len(east), len(sites), len(UNIT_SIZES)
    plant, rent = np.zeros(nb), np.zeros(nb)
    n = np.zeros((ns, nu), dtype=int)
    spare = np.zeros(ns)
    site_feeds = {s: [] for s in range(ns)}
    is_open = np.zeros(nb, dtype=bool)
    spend, left = 0.0, cap
    big = UNIT_SIZES[-1]
    order = sorted(range(nb), key=lambda b: (not east.patient_care[b], -east.criticality_weight[b] / max(east.peak_tons[b], 1)))
    for b in order:
        need = float(east.min_share[b] * east.peak_tons[b])
        take = min(left, need)
        plant[b], left = take, left - take
        short = need - take
        given = []  # (site, tons, opened_new_unit)
        for s in np.where(reach[:, b])[0]:
            while short > 1e-6:
                opened = False
                if spare[s] <= 1e-6:
                    worth = east.patient_care[b] or east.criticality_weight[b] * inp.value_per_weight_usd >= units[big]["usd_per_day"]
                    budget_ok = inp.budget_usd_per_day is None or spend + units[big]["usd_per_day"] <= inp.budget_usd_per_day
                    if n[s].sum() >= sites.max_units[s] or not worth or not budget_ok:
                        break
                    n[s, nu - 1] += 1
                    spare[s] += big
                    spend += units[big]["usd_per_day"]
                    opened = True
                g = min(spare[s], short)
                spare[s] -= g
                short -= g
                given.append((s, g, opened))
        if short <= 1e-6 or east.patient_care[b]:
            is_open[b] = True
            for s, g, _ in given:
                rent[b] += g
                site_feeds[s].append((b, g))
        else:  # can't keep it open: give the water back
            left += plant[b]
            plant[b] = 0.0
            for s, g, opened in given:
                spare[s] += g
    for s in range(ns):  # return rented units nobody ended up using
        while n[s, nu - 1] > 0 and spare[s] >= big - 1e-6:
            n[s, nu - 1] -= 1
            spare[s] -= big
    for b in order:  # top up open buildings with leftover plant water
        if is_open[b] and left > 1e-6:
            extra = min(left, east.peak_tons[b] - plant[b] - rent[b])
            if extra > 0:
                plant[b] += extra
                left -= extra
    return plant, rent, n, is_open, site_feeds, "greedy"


def _replay_temps(hz, east, plant, rent, is_open):
    """Hour by hour indoor temperature with the chosen allocation (first-order heat-up)."""
    temps = np.full(len(east), BASE_INDOOR_F)
    peak = temps.copy()
    hourly = []
    supply = plant + rent
    for t, lf in zip(hz.index, hz.load_factor):
        load = east.design_cooling_tons.to_numpy() * lf
        share = np.minimum(1.0, supply / np.maximum(load, 1e-6))
        target = BASE_INDOOR_F + INDOOR_RISE_AT_DESIGN_F * (1 - share) * lf
        temps = temps + 0.35 * (target - temps)  # buildings take a few hours to heat up
        peak = np.maximum(peak, np.where(is_open, temps, peak))
        hourly.append(dict(timestamp=str(t), outdoor_f=round(float(hz.outdoor_temp_f[t]), 1),
                           load_tons=round(float(load.sum())), served_tons=round(float(np.minimum(supply, load).sum()))))
    return peak, hourly


def plan_emergency(ds: Dataset, inp: PlanInputs | None = None, cost: CostParams | None = None) -> Plan:
    inp, cost = inp or PlanInputs(), cost or CostParams()
    hz, peak_t, lf_peak, east, sites, reach = _problem(ds, inp)
    cap = _east_capacity(ds, inp, hz)
    units = {sz: cost.unit(sz) for sz in UNIT_SIZES}
    t = time.perf_counter()
    solver_note = ""
    if inp.solver in ("auto", "milp"):
        try:
            result = _solve_milp(east, sites, reach, cap, units, inp)
        except Exception as e:  # noqa: BLE001 - any solver failure falls back
            if inp.solver == "milp":
                raise
            solver_note = f" (MILP failed: {e}; used greedy)"
            result = _solve_greedy(east, sites, reach, cap, units, inp)
    else:
        result = _solve_greedy(east, sites, reach, cap, units, inp)
    plant, rent, n, is_open, feeds, solver = result
    ms = (time.perf_counter() - t) * 1000
    peak_in, hourly = _replay_temps(hz, east, plant, rent, is_open)

    rows = []
    for b, r in east.iterrows():
        share = min(1.0, (plant[b] + rent[b]) / max(r.peak_tons, 1e-6))
        if not is_open[b]:
            why = (f"Closed: would reach about {BASE_INDOOR_F + INDOOR_RISE_AT_DESIGN_F * (1 - share) * lf_peak:.0f} °F, "
                   f"above its {r.max_indoor_temp_f:.0f} °F limit, and keeping it open is not worth a rented chiller.")
        elif r.patient_care:
            why = "Patient care: always fully cooled."
        elif rent[b] > 0:
            why = f"Open with {rent[b]:,.0f} tons from a rented chiller."
        else:
            why = "Open on plant water."
        rows.append(dict(building_id=r.building_id, name=r["name"], use=r.use, weight=int(r.criticality_weight),
                         need_tons=round(float(r.peak_tons)), plant_tons=round(float(plant[b])),
                         rental_tons=round(float(rent[b])), served_pct=round(100 * share),
                         status="open" if is_open[b] else "closed",
                         peak_indoor_f=round(float(peak_in[b]), 1) if is_open[b] else None,
                         max_indoor_f=float(r.max_indoor_temp_f), why=why))
    placements, cost_day, diesel, co2, n_units, tons = [], 0.0, 0.0, 0.0, 0, 0
    bname = east["name"]
    for s, srow in sites.iterrows():
        for u, sz in enumerate(UNIT_SIZES):
            if n[s, u] > 0:
                k = int(n[s, u])
                cost_day += k * units[sz]["usd_per_day"]
                diesel += k * units[sz]["diesel_gal_per_day"]
                co2 += k * units[sz]["co2_t_per_day"]
                n_units += k
                tons += k * sz
                placements.append(dict(site_id=srow.site_id, lat=float(srow.lat), lon=float(srow.lon),
                                       near=srow.near_building, units=k, unit_tons=sz,
                                       feeds=[dict(building=bname[b], tons=round(float(v))) for b, v in feeds[s]],
                                       usd_per_day=round(k * units[sz]["usd_per_day"])))
    open_n = int(is_open.sum())
    status = "ok" if solver.startswith("milp") else "ok (fallback)"
    plan = Plan(inputs=asdict(inp), solver=solver + solver_note, solve_ms=round(ms, 1), solve_status=status,
                plant_capacity_tons=round(cap), peak_hour=str(peak_t),
                peak_outdoor_f=round(float(hz.outdoor_temp_f.max()), 1),
                east_demand_tons=round(float(east.peak_tons.sum())), buildings=rows, placements=placements,
                cost_usd_per_day=round(cost_day), diesel_gal_per_day=round(diesel), co2_t_per_day=round(co2, 1),
                rented_units=n_units, rented_tons=tons, kept_open=open_n, closed=len(east) - open_n,
                hourly=hourly)
    plan.summary = summarize(plan)
    return plan


def summarize(plan: Plan) -> str:
    """Plain-language summary built only from the plan's own numbers (no invented figures)."""
    closed = [b["name"] for b in plan.buildings if b["status"] == "closed"]
    lo, hi = plan.uw_actual_usd_per_day
    cmp = ("below" if plan.cost_usd_per_day < lo else "within" if plan.cost_usd_per_day <= hi else "above")
    s = (f"Peak hour {plan.peak_hour[5:16]} at {plan.peak_outdoor_f:.0f} °F: east campus needs "
         f"{plan.east_demand_tons:,} tons but only {plan.plant_capacity_tons:,} tons of plant water can reach it. "
         f"Rent {plan.rented_units} chillers ({plan.rented_tons:,} tons) at {len(plan.placements)} sites for about "
         f"${plan.cost_usd_per_day:,}/day and {plan.diesel_gal_per_day:,} gallons of diesel/day. "
         f"{plan.kept_open} of {plan.kept_open + plan.closed} buildings stay open")
    s += f"; close {', '.join(closed[:6])}{'…' if len(closed) > 6 else ''}." if closed else "."
    s += f" That is {cmp} UW's estimated ${lo/1000:.0f}K–${hi/1000:.0f}K/day in 2026. Solver: {plan.solver}."
    return s

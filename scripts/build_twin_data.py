"""Build the BadgerTwin demo dataset: buildings, simplified chilled-water network,
EPANET hydraulic replay of a growing leak + June 17 burst, simulated sensor data,
asset/work-order history, emergency-plan inputs and a rental cost model.

Everything this script outputs that is not copied from a public source is SIMULATED
and labelled as such (column `data_origin`). Re-run: .venv/bin/python scripts/build_twin_data.py
"""
from __future__ import annotations

import difflib
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import wntr

ROOT = Path(__file__).resolve().parents[1] / "data"
RAW, CUR, SIM = ROOT / "raw", ROOT / "curated", ROOT / "simulated"
SIM.mkdir(parents=True, exist_ok=True)
RNG = np.random.default_rng(1980)  # fixed seed: the dataset is reproducible

SIM_START = pd.Timestamp("2026-06-01 00:00")
SIM_END = pd.Timestamp("2026-08-15 23:00")
LEAK_START = pd.Timestamp("2026-06-07 06:00")
BURST = pd.Timestamp("2026-06-17 14:00")
ISOLATED = pd.Timestamp("2026-06-17 20:00")  # crews close valves around the break
REPAIRED = pd.Timestamp("2026-08-10 06:00")

# Cooling intensity, ft² per ton at design day (rule-of-thumb ranges; assumption).
SQFT_PER_TON = {"lab": 250, "clinic": 275, "animal": 230, "library": 350, "classroom": 375,
                "office": 400, "athletics": 450, "garage": 1500, "other": 400}
# Criticality weights for the emergency planner (assumption, mirrors UW FAQ priorities:
# patient care > youth/research > in-person instruction > other).
CRIT = {"clinic": 10, "animal": 9, "lab": 7, "library": 4, "classroom": 5,
        "office": 3, "athletics": 2, "garage": 1, "other": 2}
MAX_INDOOR_F = {"clinic": 75, "animal": 78, "lab": 80, "library": 82, "classroom": 82,
                "office": 84, "athletics": 86, "garage": 95, "other": 85}

EXTRA_BUILDINGS = [  # unaffected buildings kept in the model for contrast (name in OSM, use)
    ("Memorial Union", "other"), ("Union South", "other"), ("Chemistry Building", "lab"),
    ("Computer Sceinces Building", "classroom"), ("Morgridge Hall", "classroom"),
    ("Engineering Centers Building", "lab"), ("Mechanical Engineering Building", "lab"),
    ("Microbial Sciences Building", "lab"), ("Health Sciences Learning Center", "classroom"),
    ("Memorial Library", "library"), ("Helen C. White Hall", "library"),
    ("Wisconsin Institutes for Medical Research", "clinic"),
    ("Wisconsin Institute for Discovery", "lab"), ("Kohl Center", "athletics"),
    ("Rennebohm Hall", "lab"), ("DeLuca Biochemistry Building", "lab"),
]
OSM_ALIASES = {
    "Armory & Gymnasium (Red Gym)": "Armory and Gymnasium",
    "Fleet & Service Garage": "Fleet and Service Garage",
    "Henry Taylor Hall": "Taylor Hall",
    "Kurt F. Wendt Commons": "Wendt Commons",
    "William S. Middleton Building": "William S. Middleton Office Building",
    "W. J. Brogden Psychology Building": "Brogden Psychology Building",
    "University Club (432 East Campus Mall)": "University Club",
    "Below Alumni Center (One Alumni Place)": "Martin and Florence Below Alumni Center",
}
ADDRESS_ONLY = {"21 N. Park Street": "21 North Park Street, Madison, WI",
                "45 N. Charter Street": "45 North Charter Street, Madison, WI",
                "445 Henry Mall": "445 Henry Mall, Madison, WI",
                "Below Alumni Center (One Alumni Place)": "650 North Lake Street, Madison, WI"}


# ---------------------------------------------------------------- helpers
def footprint_m2(geom: list[dict]) -> float:
    """Polygon area (m²) from OSM lat/lon geometry using a local equirectangular projection."""
    if not geom or len(geom) < 3:
        return float("nan")
    lat0 = math.radians(np.mean([p["lat"] for p in geom]))
    xs = [math.radians(p["lon"]) * 6371000 * math.cos(lat0) for p in geom]
    ys = [math.radians(p["lat"]) * 6371000 for p in geom]
    return abs(sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(len(xs)))) / 2


def haversine_m(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def nominatim(q: str):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "BadgerTwin-hackathon/1.0 (student project)"})
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    res = json.load(urllib.request.urlopen(req, timeout=30))
    return (float(res[0]["lat"]), float(res[0]["lon"])) if res else None


def norm_use(raw: str | float, name: str) -> str:
    s = f"{raw} {name}".lower() if isinstance(raw, str) else name.lower()
    for key, use in [("clinic", "clinic"), ("medical sciences", "clinic"), ("animal", "animal"),
                     ("stock pavilion", "animal"), ("taylor", "animal"), ("lab", "lab"),
                     ("mcardle", "lab"), ("bardeen", "lab"), ("service memorial", "lab"),
                     ("middleton", "lab"), ("bradley", "lab"), ("hiram smith", "lab"),
                     ("henry mall", "lab"), ("library", "library"), ("commons", "library"),
                     ("garage", "garage"), ("athletic", "athletics"), ("gym", "athletics"),
                     ("classroom", "classroom"), ("music", "classroom"), ("radio", "office"),
                     ("office", "office")]:
        if key in s:
            return use
    return "office"


# ---------------------------------------------------------------- 1. buildings
def build_buildings() -> pd.DataFrame:
    osm = json.load(open(RAW / "osm_campus_named_buildings.json"))["elements"]
    by_name: dict[str, dict] = {}
    for e in osm:
        n = e.get("tags", {}).get("name")
        if n and "geometry" in e and (n not in by_name or footprint_m2(e["geometry"]) > footprint_m2(by_name[n]["geometry"])):
            by_name[n] = e
    plants_osm = [e for e in osm if e.get("tags", {}).get("power") == "plant"]

    aff = pd.read_csv(CUR / "affected_buildings_2026.csv", dtype=str)
    rows = [dict(name=r.building_name, uw_building_number=r.uw_building_number, status_2026=r.status_jun29,
                 use=norm_use(r.primary_use, r.building_name), affected_2026=True) for r in aff.itertuples()]
    rows += [dict(name=n, uw_building_number=None, status_2026="normal", use=u, affected_2026=False)
             for n, u in EXTRA_BUILDINGS]

    out = []
    for r in rows:
        key = OSM_ALIASES.get(r["name"], r["name"])
        match = by_name.get(key) or by_name.get((difflib.get_close_matches(key, list(by_name), 1, 0.85) or [None])[0])
        if match:
            g = match["geometry"]
            lat, lon = np.mean([p["lat"] for p in g]), np.mean([p["lon"] for p in g])
            area = footprint_m2(g)
            levels = match["tags"].get("building:levels")
            loc_src = f"OpenStreetMap way {match['id']}"
        else:
            ll = nominatim(ADDRESS_ONLY.get(r["name"], r["name"] + ", Madison, WI"))
            lat, lon = ll if ll else (np.nan, np.nan)
            area, levels, loc_src = np.nan, None, "Nominatim geocode (no OSM footprint)"
        try:
            levels = float(str(levels).split(";")[0])
        except ValueError:
            levels = None
        levels = levels or 4.0  # assumption when OSM has no level count
        area = area if area == area else 1500.0  # assumption: 1,500 m² footprint when unknown
        gsf = area * 10.7639 * levels
        out.append({**r, "lat": round(lat, 6), "lon": round(lon, 6), "footprint_m2": round(area),
                    "levels": levels, "est_gsf": round(gsf),
                    "design_cooling_tons": round(gsf / SQFT_PER_TON[r["use"]]),
                    "criticality_weight": CRIT[r["use"]], "max_indoor_temp_f": MAX_INDOOR_F[r["use"]],
                    "patient_care": r["use"] == "clinic", "animal_research": r["use"] == "animal",
                    "location_source": loc_src,
                    "data_origin": "public list (Channel 3000 / UW) + OSM footprint; loads and weights ESTIMATED"})
    b = pd.DataFrame(out)
    b.insert(0, "building_id", [f"B{i:03d}" for i in range(1, len(b) + 1)])
    return b, plants_osm


# ---------------------------------------------------------------- 2. network
PLANTS = [  # id, name, lat, lon, chillers [(tons, type, install_year)] — capacities are ASSUMPTIONS
    ("P1", "Charter Street Heating & Cooling Plant", 43.0703314, -89.4051421,
     [(8000, "steam turbine centrifugal", 2015), (8500, "steam turbine centrifugal", 2015),
      (4000, "electric centrifugal", 1998), (4000, "electric centrifugal", 1991)]),
    ("P2", "Walnut Street Heating & Cooling Plant", 43.0744031, -89.4242481,
     [(3000, "steam turbine centrifugal", 1997), (3000, "steam turbine centrifugal", 1997)]),
    ("P3", "West Campus Cogeneration Facility", 43.0750, -89.42389,
     [(5000, "electric centrifugal", 2005), (5000, "electric centrifugal", 2005),
      (5000, "electric centrifugal", 2005), (5000, "electric centrifugal", 2005),
      (5000, "electric centrifugal", 2012), (5000, "electric centrifugal", 2012)]),
]


def kmeans(pts: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means (no extra dependency). Returns centroids and labels."""
    cent = pts[RNG.choice(len(pts), k, replace=False)]
    for _ in range(50):
        lab = np.argmin(((pts[:, None, :] - cent[None]) ** 2).sum(-1), axis=1)
        cent = np.array([pts[lab == i].mean(0) if (lab == i).any() else cent[i] for i in range(k)])
    return cent, lab


def build_network(b: pd.DataFrame):
    """Two service zones. East zone (the 34 buildings affected in 2026) is fed by Charter St
    through the 48-in main CW-M01; west zone by Walnut St + West Campus Cogen. The zones meet
    only through two 8-in crossovers, so isolating CW-M01 starves the east zone (as in 2026).
    Pipe routes are not public: this topology is an APPROXIMATION built from plant/building locations."""
    nodes = {p[0]: (p[2], p[3]) for p in PLANTS}
    hubs, lateral_hub, edges = {}, {}, []
    for zone, mask, k, start in (("east", b.affected_2026, 7, 1), ("west", ~b.affected_2026, 5, 8)):
        zb = b[mask]
        cent, lab = kmeans(zb[["lat", "lon"]].to_numpy(), k)
        zh = {f"J{start + i:02d}": tuple(c) for i, c in enumerate(cent)}
        hubs |= zh
        lateral_hub |= {bid: f"J{start + l:02d}" for bid, l in zip(zb.building_id, lab)}
        g = nx.Graph()
        for a in zh:
            for c in zh:
                if a < c:
                    g.add_edge(a, c, w=haversine_m(zh[a], zh[c]))
        mst = nx.minimum_spanning_tree(g, weight="w")
        extra = sorted((d["w"], u, v) for u, v, d in g.edges(data=True) if not mst.has_edge(u, v))
        for w, u, v in extra[:2]:  # close loops inside the zone
            mst.add_edge(u, v, w=w)
        edges += [(u, v, d["w"], 30, "trunk") for u, v, d in mst.edges(data=True)]
        feeders = ["P1"] if zone == "east" else ["P2", "P3"]
        for f in feeders:
            h = min(zh, key=lambda x: haversine_m(nodes[f], zh[x]))
            edges.append((f, h, haversine_m(nodes[f], zh[h]), 48 if f == "P1" else 36, "main" if f == "P1" else "trunk"))
    nodes |= hubs
    east = [h for h in hubs if int(h[1:]) <= 7]
    west = [h for h in hubs if int(h[1:]) >= 8]
    cross = sorted((haversine_m(hubs[e], hubs[w]), e, w) for e in east for w in west)
    used = set()
    for d, e, w in cross:
        if len(used) == 2:
            break
        if e not in {u[0] for u in used}:
            used.add((e, w))
            edges.append((e, w, d, 8, "crossover"))

    pipes = []
    for i, (u, v, w, diam, role) in enumerate(sorted(edges, key=lambda e: e[2]), 1):
        pid = "CW-M01" if role == "main" else (f"CW-X{i:02d}" if role == "crossover" else f"CW-T{i:02d}")
        pipes.append(dict(pipe_id=pid, from_node=u, to_node=v, length_ft=round(w * 3.28084 * 1.15 + 50),
                          diameter_in=diam, role="trunk" if role != "crossover" else "crossover"))
    # Laterals: each building to its zone hub, sized by peak flow (2 gpm/ton at 12 F dT, <=6.5 ft/s).
    for bid, lat, lon, tons in b[["building_id", "lat", "lon", "design_cooling_tons"]].itertuples(index=False):
        h = lateral_hub[bid]
        gpm = tons * 2.0
        dia = next(d for d in (6, 8, 10, 12, 14, 16, 18, 20, 24) if gpm / (2.448 * d * d) <= 6.5 or d == 24)
        pipes.append(dict(pipe_id=f"CW-L{bid[1:]}", from_node=h, to_node=bid,
                          length_ft=round(haversine_m((lat, lon), hubs[h]) * 3.28084 * 1.2 + 30),
                          diameter_in=dia, role="lateral"))
        nodes[bid] = (lat, lon)
    pipes = pd.DataFrame(pipes)

    # Asset attributes (ASSUMED): install year, material, depth, soil — features for equipment health.
    n = len(pipes)
    pipes["install_year"] = np.where(pipes.pipe_id == "CW-M01", 1966, RNG.choice([1962, 1968, 1975, 1984, 1992, 2001, 2009, 2016], n))
    pipes["material"] = np.where(pipes.install_year < 1990, "concrete-coated steel", RNG.choice(["ductile iron", "HDPE", "steel"], n))
    pipes["depth_ft"] = np.where(pipes.pipe_id == "CW-M01", 20, RNG.uniform(6, 16, n).round(1))
    pipes["soil"] = RNG.choice(["silty clay", "sandy fill", "glacial till"], n)
    pipes["in_tunnel"] = RNG.random(n) < 0.15
    pipes.loc[pipes.pipe_id == "CW-M01", "in_tunnel"] = False
    pipes["route_confidence"] = "approximate"
    pipes["data_origin"] = "SIMULATED topology from public plant/building locations"
    return nodes, hubs, pipes


# ---------------------------------------------------------------- 3. weather + demand
def load_weather() -> pd.DataFrame:
    w = json.load(open(RAW / "weather_madison_2026_hourly.json"))["hourly"]
    w = pd.DataFrame(w).rename(columns={"time": "timestamp"})
    w["timestamp"] = pd.to_datetime(w.timestamp)
    return w.set_index("timestamp").loc[SIM_START:SIM_END]


def load_factor(temp_f: pd.Series, idx: pd.DatetimeIndex) -> np.ndarray:
    """Fraction of design load: weather-driven + occupancy (weekday 7am-7pm) + base load."""
    weather = np.clip((temp_f.to_numpy() - 55) / (92 - 55), 0, 1.15)
    occ = np.where((idx.dayofweek < 5) & (idx.hour >= 7) & (idx.hour < 19), 1.0, 0.7)
    return np.clip(0.18 + 0.82 * weather * occ, 0.15, 1.15)


# ---------------------------------------------------------------- 4. hydraulics
def simulate(nodes, pipes, b, wx):
    """EPANET extended-period run, hourly. Supply side only (return side mirrors it)."""
    hours = len(wx)
    lf = load_factor(wx.temperature_2m, wx.index)
    wn = wntr.network.WaterNetworkModel()
    wn.options.time.duration = (hours - 1) * 3600
    wn.options.time.hydraulic_timestep = 3600
    wn.options.time.pattern_timestep = 3600
    wn.options.hydraulic.inpfile_units = "GPM"
    wn.options.hydraulic.demand_model = "PDD"
    wn.options.hydraulic.required_pressure = 24.0   # m (~35 psi) building ΔP needed for full flow
    wn.options.hydraulic.minimum_pressure = 5.0

    t = wx.index
    leak_frac = np.clip((t - LEAK_START) / (BURST - LEAK_START), 0, 1)
    # 1980-style growth: losses go from ~0 to ~70 gpm (≈100,000 gal/day) over ~10 days, then burst.
    leak_gpm = np.where(t < BURST, 70 * leak_frac ** 2.2, np.where(t < ISOLATED, 4500, 0.0))
    wn.add_pattern("LOAD", list(lf))
    wn.add_pattern("LEAK", list(np.maximum(leak_gpm / 4500, 0)))

    elev = 0.0
    for nid, (lat, lon) in nodes.items():
        if nid.startswith("P"):
            wn.add_curve(nid + "_CURVE", "HEAD", [(0.0, 60.0), (2.0, 45.0), (4.0, 15.0)])  # m3/s vs m
            wn.add_reservoir(nid + "_SRC", base_head=5.0)
            wn.add_junction(nid, elevation=elev)
            wn.add_pump(nid + "_PUMP", nid + "_SRC", nid, pump_type="HEAD", pump_parameter=nid + "_CURVE")
        else:
            wn.add_junction(nid, elevation=elev)
        wn.get_node(nid).coordinates = (lon, lat)
    gpm_to_m3s = 6.309e-5
    for r in b.itertuples():
        j = wn.get_node(r.building_id)
        j.demand_timeseries_list[0].base_value = r.design_cooling_tons * 2.0 * gpm_to_m3s
        j.demand_timeseries_list[0].pattern_name = "LOAD"

    # Split the 48-in main to host the leak node mid-pipe.
    main = pipes.set_index("pipe_id").loc["CW-M01"]
    a, c = nodes[main.from_node], nodes[main.to_node]
    wn.add_junction("LEAK_X", elevation=elev, coordinates=((a[1] + c[1]) / 2, (a[0] + c[0]) / 2))
    wn.get_node("LEAK_X").add_demand(4500 * gpm_to_m3s, "LEAK")
    for p in pipes.itertuples():
        L = p.length_ft * 0.3048
        D = p.diameter_in * 0.0254
        rough = 100 if p.material == "concrete-coated steel" else 130
        if p.pipe_id == "CW-M01":
            wn.add_pipe("CW-M01a", p.from_node, "LEAK_X", L / 2, D, rough)
            wn.add_pipe("CW-M01b", "LEAK_X", p.to_node, L / 2, D, rough)
        else:
            wn.add_pipe(p.pipe_id, p.from_node, p.to_node, L, D, rough)
    # Isolation: valves around the break close from ISOLATED until REPAIRED.
    for seg in ("CW-M01a", "CW-M01b"):
        for when, status in ((ISOLATED, "CLOSED"), (REPAIRED, "OPEN")):
            act = wntr.network.controls.ControlAction(wn.get_link(seg), "status",
                                                      wntr.network.LinkStatus[status.capitalize()])
            cond = wntr.network.controls.SimTimeCondition(wn, "=", int((when - SIM_START).total_seconds()))
            wn.add_control(f"{seg}_{status}_{when:%m%d}", wntr.network.controls.Control(cond, act))

    wntr.network.write_inpfile(wn, str(SIM / "badgertwin_network.inp"))
    res = wntr.sim.EpanetSimulator(wn).run_sim()
    return wn, res, leak_gpm, lf


# ---------------------------------------------------------------- 5. sensors
def sensors(wn, res, leak_gpm, lf, wx, b, pipes):
    t = wx.index
    m3s_to_gpm = 1 / 6.309e-5
    P = res.node["pressure"] * 1.4219  # m -> psi
    Q = res.link["flowrate"] * m3s_to_gpm
    D = res.node["demand"] * m3s_to_gpm
    P.index = Q.index = D.index = t[: len(P)]

    rows, meta = [], []

    def add(sid, kind, asset, unit, series, noise, desc):
        v = series.to_numpy(dtype=float) + RNG.normal(0, noise, len(series))
        v[RNG.random(len(v)) < 0.01] = np.nan  # ~1% dropouts
        rows.append(pd.DataFrame({"timestamp": series.index, "sensor_id": sid, "value": np.round(v, 3)}))
        meta.append(dict(sensor_id=sid, sensor_type=kind, asset_id=asset, unit=unit, description=desc,
                         data_origin="SIMULATED (EPANET replay + noise)"))

    # Make-up water: baseline ~9,000 gal/day (1980 normal) + leak. This is the 1980/2005 detection signal.
    makeup = pd.Series(9000 / 24 + leak_gpm[: len(P)] * 60, index=P.index)
    add("S-MKUP-P1", "makeup_water", "P1", "gal/h", makeup, 25, "Charter St plant make-up water meter")
    for p in PLANTS:
        add(f"S-FLOW-{p[0]}", "flow", p[0], "gpm", Q[p[0] + "_PUMP"], 40, f"{p[1]} supply flow")
        add(f"S-PRES-{p[0]}", "pressure", p[0], "psi", P[p[0]], 0.3, f"{p[1]} discharge pressure")
        add(f"S-TSUP-{p[0]}", "supply_temp", p[0], "degF", pd.Series(40.0, index=P.index), 0.25, "Chilled-water supply temp")
    # Pressure sensors at every hub, flow on every trunk pipe.
    for j in [n for n in wn.junction_name_list if n.startswith("J")]:
        add(f"S-PRES-{j}", "pressure", j, "psi", P[j], 0.35, f"Pressure at junction {j}")
    for pid in [p for p in wn.link_name_list if p.startswith(("CW-T", "CW-X", "CW-M01"))]:
        add(f"S-FLOW-{pid}", "flow", pid, "gpm", Q[pid].abs(), 15, f"Flow in trunk {pid}")
    # Building meters: delivered flow, and cooling delivered vs demanded.
    for r in b.itertuples():
        delivered = D[r.building_id].clip(lower=0)
        add(f"S-BFLOW-{r.building_id}", "building_flow", r.building_id, "gpm", delivered, 3, f"{r.name} chilled-water flow")
        demand_tons = pd.Series(r.design_cooling_tons * lf[: len(P)], index=P.index)
        served = np.minimum(delivered / 2.0, demand_tons)
        indoor = 72 + np.clip(demand_tons - served, 0, None) / max(r.design_cooling_tons, 1) * 22  # crude heat-up
        add(f"S-TIN-{r.building_id}", "indoor_temp", r.building_id, "degF", indoor.rolling(6, min_periods=1).mean(), 0.4,
            f"{r.name} average indoor temperature")

    ts = pd.concat(rows)
    # One labelled false alarm: a pressure transducer glitch on June 3 (no leak).
    fa = (ts.sensor_id == "S-PRES-J03") & ts.timestamp.between("2026-06-03 02:00", "2026-06-03 05:00")
    ts.loc[fa, "value"] = ts.loc[fa, "value"] - 9
    labels = pd.DataFrame([
        dict(event_id="EV-01", start="2026-06-03 02:00", end="2026-06-03 05:00", kind="false_alarm",
             asset_id="J03", note="Sensor glitch injected; detector should NOT open an incident"),
        dict(event_id="EV-02", start=str(LEAK_START), end=str(BURST), kind="slow_leak", asset_id="CW-M01",
             note="Concrete coating spalls off 48-in steel main; leak grows ~0→70 gpm (1980 pattern)"),
        dict(event_id="EV-03", start=str(BURST), end=str(ISOLATED), kind="burst", asset_id="CW-M01",
             note="Main ruptures (~4,500 gpm loss) on the hot afternoon of June 17"),
        dict(event_id="EV-04", start=str(ISOLATED), end=str(REPAIRED), kind="isolation", asset_id="CW-M01",
             note="Segment valved off; east loop fed only via crossovers → reduced cooling"),
    ])
    return ts, pd.DataFrame(meta), labels


# ---------------------------------------------------------------- 6. assets, work orders, plan inputs
def assets_and_history(pipes, b):
    chillers, pumps = [], []
    for pid, name, lat, lon, ch in PLANTS:
        for i, (tons, kind, yr) in enumerate(ch, 1):
            kw_ton = 0.55 + 0.006 * (2026 - yr) + RNG.normal(0, 0.03)  # older units drift up (assumption)
            chillers.append(dict(chiller_id=f"{pid}-CH{i}", plant_id=pid, capacity_tons=tons, type=kind,
                                 install_year=yr, design_kw_per_ton=0.55, current_kw_per_ton=round(kw_ton, 3),
                                 data_origin="ASSUMED (Charter 8,000/8,500-ton units are public; rest assumed)"))
        for i in range(1, 4):
            pumps.append(dict(pump_id=f"{pid}-PMP{i}", plant_id=pid, hp=RNG.choice([500, 750, 1000]),
                              install_year=int(RNG.choice([1991, 1998, 2005, 2012, 2019])),
                              vibration_baseline_ips=round(RNG.uniform(0.08, 0.15), 3), data_origin="ASSUMED"))
    valves = [dict(valve_id=f"V-{i:02d}", pipe_id=p, position="open", type="butterfly isolation",
                   exercised_last=str(pd.Timestamp("2019-01-01") + pd.Timedelta(days=int(RNG.integers(0, 2600))))[:10],
                   data_origin="SIMULATED")
              for i, p in enumerate(pipes[pipes.role == "trunk"].pipe_id.repeat(2), 1)]

    wo, types = [], ["leak repair", "valve exercise", "pump bearing", "chiller tube cleaning",
                     "insulation repair", "coil freeze damage", "meter calibration", "excavation inspection"]
    assets = list(pipes.pipe_id) + [c["chiller_id"] for c in chillers] + [p["pump_id"] for p in pumps]
    for i in range(1, 421):
        a = RNG.choice(assets)
        typ = RNG.choice(types)
        opened = pd.Timestamp("2014-01-01") + pd.Timedelta(days=int(RNG.integers(0, 4500)))
        wo.append(dict(work_order_id=f"WO-{i:05d}", asset_id=a, type=typ,
                       priority=RNG.choice(["routine", "urgent", "emergency"], p=[0.7, 0.22, 0.08]),
                       opened=opened.date(), closed=(opened + pd.Timedelta(days=int(RNG.integers(1, 60)))).date(),
                       cost_usd=int(RNG.lognormal(8.5, 1.1)),
                       preventive=typ in ("valve exercise", "chiller tube cleaning", "meter calibration"),
                       data_origin="SIMULATED"))
    # The historical incidents as real work orders on the matching assets (public facts).
    wo += [dict(work_order_id="WO-H1980", asset_id="CW-M01", type="leak repair", priority="emergency",
                opened="1980-06-09", closed="1980-06-20", cost_usd=None, preventive=False,
                data_origin="PUBLIC FACT (1980 48-in main leak; dates approximate)"),
           dict(work_order_id="WO-H2026", asset_id="CW-M01", type="main break", priority="emergency",
                opened="2026-06-17", closed="2026-08-10", cost_usd=15_800_000, preventive=False,
                data_origin="PUBLIC FACT (Cap Times Oct 8 2026: $15.8M total)")]

    # Candidate temporary-chiller sites near affected buildings (lots/malls; ASSUMED).
    aff = b[b.affected_2026]
    sites = []
    for i, r in enumerate(aff.sort_values("criticality_weight", ascending=False).head(14).itertuples(), 1):
        sites.append(dict(site_id=f"TC-{i:02d}", near_building_id=r.building_id, near_building=r.name,
                          lat=r.lat + 0.0004, lon=r.lon + 0.0004, max_units=int(RNG.choice([1, 2, 2, 3])),
                          unit_tons_options="300|400|500", generator_kw_per_unit=750, setup_cost_usd=int(RNG.uniform(20e3, 70e3)),
                          data_origin="ASSUMED candidate site"))
    return (pd.DataFrame(chillers), pd.DataFrame(pumps), pd.DataFrame(valves), pd.DataFrame(wo), pd.DataFrame(sites))


def research_weights(b):
    """Department-level NIH/NSF $ (real, public) to justify criticality; mapping to buildings is ASSUMED."""
    nih = pd.read_csv(RAW / "nih_uwm_awards_fy2025_2026.csv")
    dept = nih.groupby("dept_type", dropna=True).award_amount_usd.sum().sort_values(ascending=False).reset_index()
    dept.columns = ["nih_dept_type", "nih_award_usd_fy25_26"]
    building_map = {"McArdle Building": "ONCOLOGY", "Medical Sciences Center": "PHYSIOLOGY",
                    "Bardeen Medical Laboratories": "ANATOMY/CELL BIOLOGY", "Service Memorial Institute": "PHYSIOLOGY",
                    "W. J. Brogden Psychology Building": "PSYCHOLOGY", "Wisconsin Institutes for Medical Research": "INTERNAL MEDICINE/MEDICINE",
                    "Microbial Sciences Building": "MICROBIOLOGY/IMMUN/VIROLOGY", "Rennebohm Hall": "PHARMACOLOGY",
                    "Henry Taylor Hall": "VETERINARY SCIENCES", "Health Sciences Learning Center": "PUBLIC HEALTH & PREV MEDICINE"}
    m = pd.DataFrame([dict(building=k, nih_dept_type=v) for k, v in building_map.items()]).merge(dept, how="left")
    m["mapping_origin"] = "ASSUMED building↔department mapping; $ are real NIH RePORTER totals"
    return dept, m


def cost_model():
    """Monte Carlo of daily temporary-cooling cost (market prices; mirrors the pitch's assumptions)."""
    n = 200_000
    units = RNG.integers(28, 33, n)
    tons = RNG.uniform(300, 500, n)
    rent_wk = 8666 * (tons / 500) * RNG.uniform(0.9, 1.5, n)
    kw_ton = RNG.uniform(0.95, 1.30, n)
    load = RNG.uniform(0.55, 0.85, n)
    gen_kw = tons * kw_ton * 1.15
    gen_rent_wk = np.interp(gen_kw, [750, 1000], [4800, 5640]) * 2  # 24/7 = double shift
    gal_h = np.interp(load, [0.5, 0.75, 1.0], [27.4, 39.3, 51.0]) * gen_kw / 750
    diesel = RNG.uniform(4.40, 5.10, n)
    daily = units * (rent_wk / 7 + gen_rent_wk / 7 + gal_h * 24 * diesel)
    fuel = units * gal_h * 24
    q = np.percentile(daily, [10, 50, 90])
    summary = pd.DataFrame([
        dict(metric="temp_cooling_cost_usd_per_day", p10=q[0], p50=q[1], p90=q[2]),
        dict(metric="diesel_gal_per_day", p10=np.percentile(fuel, 10), p50=np.median(fuel), p90=np.percentile(fuel, 90)),
        dict(metric="co2_tonnes_per_day", p10=np.percentile(fuel, 10) * 10.21 / 1000,
             p50=np.median(fuel) * 10.21 / 1000, p90=np.percentile(fuel, 90) * 10.21 / 1000),
        dict(metric="days_10M_lasts", p10=10e6 / q[2], p50=10e6 / q[1], p90=10e6 / q[0]),
    ]).round(1)
    summary["data_origin"] = "MODELLED from market prices (see cost_assumptions.csv)"
    assumptions = pd.DataFrame([
        ("temp_chiller_units", "28-32", "UW: 'about 30'"), ("unit_size_tons", "300-500", "assumption"),
        ("chiller_rent_usd_per_week_500t", "8666 x 0.9-1.5 emergency multiplier", "KWIPPED listing"),
        ("chiller_kw_per_ton", "0.95-1.30", "typical air-cooled"), ("avg_load", "55-85%", "assumption"),
        ("generator_rent_usd_per_week", "750kW 4800 / 1000kW 5640, x2 for 24/7", "published rate card"),
        ("diesel_gal_per_h_750kW", "27.4 @50%, 39.3 @75%", "generator fuel chart"),
        ("diesel_usd_per_gal", "4.40-5.10", "FRED GASDESW (raw/diesel_us_weekly_fred_GASDESW.csv)"),
        ("co2_kg_per_gal_diesel", "10.21", "EPA"), ("setup_usd_per_unit", "20k-70k", "assumption")],
        columns=["input", "range", "basis"])
    return summary, assumptions


# ---------------------------------------------------------------- main
def main():
    b, _ = build_buildings()
    nodes, hubs, pipes = build_network(b)
    wx = load_weather()
    wn, res, leak_gpm, lf = simulate(nodes, pipes, b, wx)
    ts, sensor_meta, labels = sensors(wn, res, leak_gpm, lf, wx, b, pipes)
    chillers, pumps, valves, wo, sites = assets_and_history(pipes, b)
    dept, bmap = research_weights(b)
    cost, assumptions = cost_model()

    node_df = pd.DataFrame([dict(node_id=k, lat=v[0], lon=v[1],
                                 node_type="plant" if k.startswith("P") else "hub" if k.startswith("J") else "building")
                            for k, v in nodes.items()])
    plants = pd.DataFrame([dict(plant_id=p[0], name=p[1], lat=p[2], lon=p[3],
                                total_capacity_tons=sum(c[0] for c in p[4])) for p in PLANTS])
    plants["data_origin"] = "locations OSM/Wikipedia; capacities ASSUMED to sum to >50,000 tons (UW News)"
    hourly_demand = pd.DataFrame({"timestamp": wx.index, "outdoor_temp_f": wx.temperature_2m.values,
                                  "dew_point_f": wx.dew_point_2m.values, "campus_load_factor": lf.round(3),
                                  "modelled_campus_demand_tons": (lf * b.design_cooling_tons.sum()).round()})

    out = {"buildings.csv": b, "plants.csv": plants, "chillers.csv": chillers, "pumps.csv": pumps,
           "network_nodes.csv": node_df, "pipe_segments.csv": pipes, "valves.csv": valves,
           "sensors.csv": sensor_meta, "sensor_readings_hourly.csv": ts, "event_labels.csv": labels,
           "work_orders.csv": wo, "temp_chiller_sites.csv": sites, "weather_demand_hourly.csv": hourly_demand,
           "research_dollars_by_dept.csv": dept, "building_research_map.csv": bmap,
           "cost_model_summary.csv": cost, "cost_assumptions.csv": assumptions}
    for f, df in out.items():
        df.to_csv(SIM / f, index=False)
        print(f"{f:32s} {len(df):>8,d} rows  {(SIM / f).stat().st_size / 1e6:6.2f} MB")
    print(cost.to_string(index=False))


if __name__ == "__main__":
    main()

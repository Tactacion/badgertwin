"""GeoJSON for the map: real OSM building footprints (with heights) for our 50 buildings,
pipes as lines, plants and rental-chiller sites as points."""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .data import Dataset

LEVEL_HEIGHT_M = 4.2


@lru_cache(maxsize=1)
def _osm_ways(raw_path: str) -> dict[int, dict]:
    p = Path(raw_path)
    if not p.exists():
        return {}
    return {e["id"]: e for e in json.loads(p.read_text())["elements"] if e.get("type") == "way" and "geometry" in e}


def _square(lat: float, lon: float, half_m: float = 22.0) -> list[list[float]]:
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * math.cos(math.radians(lat)))
    return [[lon - dlon, lat - dlat], [lon + dlon, lat - dlat], [lon + dlon, lat + dlat], [lon - dlon, lat + dlat], [lon - dlon, lat - dlat]]


def buildings_geojson(ds: Dataset, data_dir: Path) -> dict:
    ways = _osm_ways(str(data_dir / "raw" / "osm_campus_named_buildings.json"))
    feats = []
    for b in ds.buildings.itertuples():
        m = re.search(r"way (\d+)", str(b.location_source))
        way = ways.get(int(m.group(1))) if m else None
        ring = [[p["lon"], p["lat"]] for p in way["geometry"]] if way else _square(b.lat, b.lon)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        height = float(b.levels) * LEVEL_HEIGHT_M
        if way:
            tag_h = way.get("tags", {}).get("height")
            try:
                height = float(str(tag_h).split()[0]) if tag_h else height
            except ValueError:
                pass
        feats.append(dict(type="Feature", id=int(b.building_id[1:]),
                          geometry=dict(type="Polygon", coordinates=[ring]),
                          properties=dict(building_id=b.building_id, name=b.name, use=b.use,
                                          affected=bool(b.affected_2026), status_2026=b.status_2026,
                                          tons=int(b.design_cooling_tons), height=round(height, 1),
                                          footprint="osm" if way else "approximate")))
    return dict(type="FeatureCollection", features=feats)


def network_geojson(ds: Dataset) -> dict:
    at = ds.nodes.set_index("node_id")[["lon", "lat"]].to_dict("index")
    pipes = []
    for p in ds.pipes.itertuples():
        a, c = at[p.from_node], at[p.to_node]
        pipes.append(dict(type="Feature", id=hash(p.pipe_id) & 0x7FFFFFFF,
                          geometry=dict(type="LineString", coordinates=[[a["lon"], a["lat"]], [c["lon"], c["lat"]]]),
                          properties=dict(pipe_id=p.pipe_id, diameter=int(p.diameter_in), role=p.role,
                                          install_year=int(p.install_year), material=p.material)))
    plants = [dict(type="Feature", geometry=dict(type="Point", coordinates=[r.lon, r.lat]),
                   properties=dict(plant_id=r.plant_id, name=r.name.replace(" Heating & Cooling Plant", "")
                                   .replace(" Heating and Cooling Plant", "").replace(" Cogeneration Facility", " Cogen")))
              for r in ds.plants.itertuples()]
    hubs = [dict(type="Feature", geometry=dict(type="Point", coordinates=[r.lon, r.lat]), properties=dict(node_id=r.node_id))
            for r in ds.nodes.itertuples() if r.node_type == "hub"]
    return dict(pipes=dict(type="FeatureCollection", features=pipes),
                plants=dict(type="FeatureCollection", features=plants),
                hubs=dict(type="FeatureCollection", features=hubs))

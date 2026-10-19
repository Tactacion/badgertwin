"""Load the BadgerTwin dataset (data/simulated + data/curated) into one immutable bundle."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Scenario anchors used across the app (they match scripts/build_twin_data.py).
BURST_TIME = pd.Timestamp("2026-06-17 14:00")
ISOLATED_TIME = pd.Timestamp("2026-06-17 20:00")
REPLAY_START = pd.Timestamp("2026-06-01 00:00")
REPLAY_END = pd.Timestamp("2026-08-15 23:00")
SIMULATED_LABEL = "Simplified, simulated data built from public facts"


def load_factor(temp_f: np.ndarray, index: pd.DatetimeIndex) -> np.ndarray:
    """Fraction of design cooling load: weather-driven, with class-hours occupancy and a base load.
    Same formula the data generator used, so planner loads match the simulated sensors."""
    weather = np.clip((np.asarray(temp_f, dtype=float) - 55) / (92 - 55), 0, 1.15)
    occ = np.where((index.dayofweek < 5) & (index.hour >= 7) & (index.hour < 19), 1.0, 0.7)
    return np.clip(0.18 + 0.82 * weather * occ, 0.15, 1.15)


@dataclass(frozen=True)
class Dataset:
    buildings: pd.DataFrame
    plants: pd.DataFrame
    chillers: pd.DataFrame
    pumps: pd.DataFrame
    nodes: pd.DataFrame
    pipes: pd.DataFrame
    valves: pd.DataFrame
    sensors: pd.DataFrame
    readings: pd.DataFrame  # long format: timestamp, sensor_id, value
    weather: pd.DataFrame
    work_orders: pd.DataFrame
    sites: pd.DataFrame
    events: pd.DataFrame
    cost_assumptions: pd.DataFrame
    cost_summary: pd.DataFrame
    research_map: pd.DataFrame
    sources: pd.DataFrame
    timeline: pd.DataFrame
    cost_facts: pd.DataFrame
    articles: dict[str, str] = field(default_factory=dict)

    @cached_property
    def wide(self) -> pd.DataFrame:
        """Readings pivoted to one column per sensor, hourly index."""
        return self.readings.pivot_table(index="timestamp", columns="sensor_id", values="value")

    def series(self, sensor_id: str) -> pd.Series:
        return self.wide[sensor_id]

    def building(self, building_id: str) -> pd.Series:
        return self.buildings.set_index("building_id").loc[building_id]

    def pipe(self, pipe_id: str) -> pd.Series:
        return self.pipes.set_index("pipe_id").loc[pipe_id]


def _csv(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, **kw) if path.exists() else pd.DataFrame()


def _events(path: Path) -> pd.DataFrame:
    ev = pd.read_csv(path)
    for c in ("start", "end"):
        ev[c] = pd.to_datetime(ev[c], format="mixed")
    return ev


def load_dataset(data_dir: Path | str = DEFAULT_DATA_DIR) -> Dataset:
    d = Path(data_dir)
    sim, cur = d / "simulated", d / "curated"
    readings = pd.read_csv(sim / "sensor_readings_hourly.csv", parse_dates=["timestamp"]).dropna(subset=["value"])
    weather = pd.read_csv(sim / "weather_demand_hourly.csv", parse_dates=["timestamp"])
    work_orders = pd.read_csv(sim / "work_orders.csv", parse_dates=["opened", "closed"])
    articles = {p.stem: p.read_text(errors="ignore") for p in sorted((d / "raw" / "articles").glob("*.txt"))}
    return Dataset(
        buildings=pd.read_csv(sim / "buildings.csv", dtype={"uw_building_number": str}),
        plants=pd.read_csv(sim / "plants.csv"),
        chillers=pd.read_csv(sim / "chillers.csv"),
        pumps=pd.read_csv(sim / "pumps.csv"),
        nodes=pd.read_csv(sim / "network_nodes.csv"),
        pipes=pd.read_csv(sim / "pipe_segments.csv"),
        valves=pd.read_csv(sim / "valves.csv"),
        sensors=pd.read_csv(sim / "sensors.csv"),
        readings=readings,
        weather=weather,
        work_orders=work_orders,
        sites=pd.read_csv(sim / "temp_chiller_sites.csv"),
        events=_events(sim / "event_labels.csv"),
        cost_assumptions=pd.read_csv(sim / "cost_assumptions.csv"),
        cost_summary=pd.read_csv(sim / "cost_model_summary.csv"),
        research_map=pd.read_csv(sim / "building_research_map.csv"),
        sources=_csv(cur / "sources.csv"),
        timeline=_csv(cur / "incident_timeline.csv"),
        cost_facts=_csv(cur / "cost_facts.csv"),
        articles=articles,
    )

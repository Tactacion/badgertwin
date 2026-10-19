"""Tool 1: leak detection.

Signal 1, water balance: a closed chilled-water loop only needs make-up water for small losses
(~9,000 gal/day in 1980). A sustained rise in make-up water means water is leaving the loop.
Signal 2, localisation: rank trunk pipes by flow imbalance between meters (where two exist),
pressure drop at their end nodes after removing the load effect, and prior pipe risk.
Signal 3, sensor-fault guard: one pressure sensor dropping while water balance is normal is a
sensor fault, not a leak.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .data import BURST_TIME, Dataset, load_factor
from .health import health_scores

MAKEUP_SENSOR = "S-MKUP-P1"
BASELINE = (pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-06 23:00"))
SIGMA_K = 4.0
CONSECUTIVE_HOURS = 3
BURST_GAL_PER_DAY = 500_000  # far beyond any slow leak
WINDOW_H = 24


@dataclass(frozen=True)
class Suspect:
    pipe_id: str
    from_node: str
    to_node: str
    score: float
    flow_imbalance_gpm: float | None
    pressure_drop_z: float
    prior_risk: float
    reason: str


@dataclass(frozen=True)
class LeakStatus:
    as_of: str
    alert: bool
    kind: str  # "normal" | "leak" | "burst" | "isolated"
    makeup_gal_per_day: float
    baseline_gal_per_day: float
    threshold_gal_per_day: float
    excess_gal_per_day: float
    first_alert_at: str | None
    hours_alerting: int
    confidence: str  # "none" | "low" | "medium" | "high"
    headline: str
    top3: list[Suspect] = field(default_factory=list)
    sensor_faults: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class LeakDetector:
    """Precomputes everything once; `at(as_of)` is then cheap enough to call every replay hour."""

    def __init__(self, ds: Dataset):
        self.ds = ds
        w = ds.wide
        mk = w[MAKEUP_SENSOR].ffill(limit=3)  # forward fill only: never uses future readings
        self.rate = mk.rolling(WINDOW_H, min_periods=20).mean() * 24  # gal/day
        base = self.rate[BASELINE[0] + pd.Timedelta(hours=WINDOW_H):BASELINE[1]]
        self.mu, self.sigma = float(base.mean()), float(base.std())
        self.threshold = self.mu + SIGMA_K * self.sigma
        above = (self.rate > self.threshold).astype(int)
        self.alerting = above.rolling(CONSECUTIVE_HOURS).sum() >= CONSECUTIVE_HOURS
        self.burst = self.rate > BURST_GAL_PER_DAY

        # Pressure residuals: remove the load effect with p = a + b*load_factor fit on the baseline.
        wx = ds.weather.set_index("timestamp")
        lf = pd.Series(load_factor(wx.outdoor_temp_f.to_numpy(), wx.index), index=wx.index).reindex(w.index)
        self.pressure_cols = [c for c in w.columns if c.startswith("S-PRES-")]
        self.z = pd.DataFrame(index=w.index)
        for c in self.pressure_cols:
            p = w[c]
            m = p[BASELINE[0]:BASELINE[1]].notna()
            x, y = lf[BASELINE[0]:BASELINE[1]][m], p[BASELINE[0]:BASELINE[1]][m]
            b, a = np.polyfit(x, y, 1)
            resid = p - (a + b * lf)
            r0 = resid[BASELINE[0]:BASELINE[1]].dropna().to_numpy()
            med = float(np.median(r0))
            mad = float(np.median(np.abs(r0 - med))) * 1.4826 or 0.3
            self.z[c] = (resid - med) / mad

        # Flow imbalance where a pipe has a meter on both sides of the leak-prone section.
        self.pairs = {"CW-M01": ("S-FLOW-CW-M01a", "S-FLOW-CW-M01b")}
        self.imb, self.imb_sd = {}, {}
        for pid, (a, b) in self.pairs.items():
            if a in w and b in w:
                d = (w[a] - w[b])
                self.imb[pid] = d
                self.imb_sd[pid] = float(d[BASELINE[0]:BASELINE[1]].std()) or 15.0

        risk = health_scores(ds, as_of=BASELINE[0])
        self.prior = risk.set_index("asset_id").risk.to_dict()
        self.trunks = ds.pipes[ds.pipes.role.isin(["trunk", "crossover"])]

    # ------------------------------------------------------------ helpers
    def _node_sensor(self, node: str) -> str | None:
        sid = f"S-PRES-{node}"
        return sid if sid in self.z else None

    def _sensor_faults(self, t0, t1) -> list[dict]:
        """Single-sensor pressure excursions while water balance is normal."""
        win = self.z.loc[t0:t1]
        if win.empty:
            return []
        faults = []
        for c in self.pressure_cols:
            bad = win[c] < -6
            others = win.drop(columns=c).median(axis=1)
            lone = bad & (others > -2)
            if lone.sum() >= 1 and not self.alerting.loc[t0:t1].any():
                faults.append(dict(sensor_id=c, first=str(win.index[lone.to_numpy()][0]),
                                   hours=int(lone.sum()),
                                   note="Only this sensor dropped and water balance is normal: likely a sensor fault, not a leak."))
        return faults

    def _localise(self, as_of: pd.Timestamp) -> list[Suspect]:
        t0 = as_of - pd.Timedelta(hours=WINDOW_H - 1)
        z = self.z.loc[t0:as_of]
        out = []
        for p in self.trunks.itertuples():
            drops = [max(0.0, -float(z[s].mean())) for s in (self._node_sensor(p.from_node), self._node_sensor(p.to_node)) if s]
            drop_z = float(np.mean(drops)) if drops else 0.0
            imb_gpm, imb_z = None, 0.0
            if p.pipe_id in self.imb:
                seg = self.imb[p.pipe_id].loc[t0:as_of].dropna()
                if len(seg):
                    imb_gpm = float(seg.mean())
                    imb_z = max(0.0, imb_gpm / (self.imb_sd[p.pipe_id] / np.sqrt(len(seg))))
            prior = float(self.prior.get(p.pipe_id, 0.1))
            score = 0.5 * min(imb_z / 5, 1) + 0.3 * min(drop_z / 3, 1) + 0.2 * prior
            bits = []
            if imb_gpm is not None and imb_z >= 2:
                bits.append(f"{imb_gpm:,.0f} gpm more water enters than leaves this pipe")
            if drop_z >= 1:
                bits.append("pressure at its ends is lower than the load explains")
            bits.append(f"{int(p.install_year)} {p.material}, {p.depth_ft:g} ft deep")
            out.append(Suspect(p.pipe_id, p.from_node, p.to_node, float(round(score, 3)),
                               None if imb_gpm is None else round(imb_gpm, 1), float(round(drop_z, 2)),
                               round(prior, 3), "; ".join(bits)))
        return sorted(out, key=lambda s: s.score, reverse=True)[:3]

    # ------------------------------------------------------------ public
    def at(self, as_of) -> LeakStatus:
        as_of = pd.Timestamp(as_of).floor("h")
        rate = float(self.rate.get(as_of, np.nan))
        hist = self.alerting.loc[:as_of]
        firsts = hist[hist & ~hist.shift(1, fill_value=False)]
        first = firsts.index[-1] if len(firsts) else None
        alert = bool(hist.iloc[-1]) if len(hist) else False
        burst = bool(self.burst.loc[:as_of].iloc[-1]) if len(hist) else False
        burst_seen = bool(self.burst.loc[:as_of].any())
        faults = self._sensor_faults(as_of - pd.Timedelta(hours=WINDOW_H - 1), as_of)

        if burst:
            kind = "burst"
        elif alert:
            kind = "leak"
        elif burst_seen:
            kind = "isolated"
        else:
            kind = "normal"
        excess = max(0.0, rate - self.mu)
        top3 = self._localise(as_of) if kind in ("leak", "burst") else []
        hours = int((as_of - first).total_seconds() // 3600) + 1 if (alert and first is not None) else 0

        if kind == "normal":
            confidence, headline = "none", "No sign of water leaving the loop."
        elif kind == "isolated":
            confidence = "high"
            headline = "The broken section is valved off. Water balance is back to normal, but east-campus cooling is reduced."
        else:
            lead = top3[0] if top3 else None
            strong = lead and lead.flow_imbalance_gpm is not None and lead.score >= 0.6
            confidence = "high" if kind == "burst" or strong else ("medium" if lead and lead.score >= 0.35 else "low")
            where = f" Most likely on {lead.pipe_id} (between {lead.from_node} and {lead.to_node})." if lead else ""
            headline = (f"Major break: about {excess:,.0f} gallons a day are leaving the loop.{where}" if kind == "burst"
                        else f"Likely leak: about {excess:,.0f} more gallons a day leaving the loop than normal.{where}")
        evidence = [f"Charter plant make-up water: {rate:,.0f} gal/day vs normal {self.mu:,.0f} ± {self.sigma:,.0f} "
                    f"(alert above {self.threshold:,.0f}). Source: sensor {MAKEUP_SENSOR}, simulated."]
        if hours:
            evidence.append(f"Above the alert line for {hours} hours in a row.")
        evidence += [f"{s.pipe_id}: {s.reason}." for s in top3]
        evidence += [f"Ignored {f['sensor_id']}: {f['note']}" for f in faults]
        return LeakStatus(str(as_of), kind in ("leak", "burst"), kind, round(rate, 0), round(self.mu, 0),
                          round(self.threshold, 0), round(excess, 0), str(first) if first is not None else None,
                          hours, confidence, headline, top3, faults, evidence)

    def makeup_series(self, start, end) -> pd.DataFrame:
        s = self.rate.loc[pd.Timestamp(start):pd.Timestamp(end)]
        return pd.DataFrame({"timestamp": s.index.astype(str), "gal_per_day": s.round(0).to_numpy()})

    def scan(self, start="2026-06-01 00:00", end="2026-06-20 00:00") -> dict:
        """Run the detector hour by hour and score it against the ground-truth event labels."""
        times = pd.date_range(start, end, freq="h")
        alert = self.alerting.reindex(times, fill_value=False)
        onsets = alert[alert & ~alert.shift(1, fill_value=False)].index
        ev = self.ds.events.set_index("kind")
        leak_win = (ev.loc["slow_leak", "start"], ev.loc["burst", "end"])
        true_onsets = [t for t in onsets if leak_win[0] <= t <= leak_win[1]]
        false_onsets = [t for t in onsets if not (leak_win[0] <= t <= leak_win[1])]
        first = true_onsets[0] if true_onsets else None
        fa = ev.loc["false_alarm"]
        glitch_faults = self._sensor_faults(fa.start, fa.end)
        top3_at_first = self._localise(first) if first is not None else []
        top3_day2 = self._localise(first + pd.Timedelta(hours=72)) if first is not None else []
        return dict(
            first_alert_at=str(first) if first is not None else None,
            burst_at=str(BURST_TIME),
            warning_hours=int((BURST_TIME - first).total_seconds() // 3600) if first is not None else 0,
            false_alarms=len(false_onsets),
            false_alarm_times=[str(t) for t in false_onsets],
            glitch_rejected=bool(glitch_faults) and not alert.loc[fa.start:fa.end].any(),
            glitch_detail=glitch_faults,
            top3_at_first_alert=[asdict(s) for s in top3_at_first],
            top3_three_days_later=[asdict(s) for s in top3_day2],
            cw_m01_in_top3_at_first=any(s.pipe_id == "CW-M01" for s in top3_at_first),
            cw_m01_rank1_three_days_later=bool(top3_day2) and top3_day2[0].pipe_id == "CW-M01",
        )

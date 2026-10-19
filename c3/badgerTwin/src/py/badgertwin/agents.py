"""The agents. Each one SUGGESTS: it returns a draft built only from data and tool results.
Nothing here changes the system; approvals happen in store.py with a named person.

These are deterministic (no LLM needed), so the demo is reliable and every number is traceable.
On C3, each function becomes a tool that a C3 Generative AI agent calls; the agent may rephrase
the text but must keep the numbers it was given.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .data import SIMULATED_LABEL, Dataset
from .health import health_scores
from .leak import LeakStatus

STOP = set("the a an of to in on and or is are was were for with at by from it this that what how why when "
           "which who did does do be been has have had near about i we you they its as not".split())


# ------------------------------------------------------------------ monitoring
def should_open_incident(status: LeakStatus, open_incidents: list[dict]) -> bool:
    """Open an incident when the detector alerts and nothing is already open for that pipe."""
    if not status.alert:
        return False
    pipe = status.top3[0].pipe_id if status.top3 else None
    return not any(i["status"] != "closed" and i.get("suspected_pipe") == pipe for i in open_incidents)


# ------------------------------------------------------------------ diagnosis
def diagnose(ds: Dataset, status: LeakStatus) -> dict:
    if not status.top3:
        return dict(text="No suspect pipe yet.", evidence=[])
    lead = status.top3[0]
    p = ds.pipe(lead.pipe_id)
    wo = ds.work_orders[(ds.work_orders.asset_id == lead.pipe_id) & (ds.work_orders.opened <= pd.Timestamp(status.as_of))]
    history = [f"{r.opened:%Y-%m-%d}: {r.type} ({r.priority})" for r in wo.sort_values("opened").itertuples()]
    is_1980_pattern = p.material == "concrete-coated steel" and status.kind == "leak"
    lines = [
        f"What we see: {status.headline}",
        f"Where: {lead.pipe_id}, a {int(p.diameter_in)}-inch {p.material} pipe from {int(p.install_year)}, "
        f"{p.depth_ft:g} ft underground, running {lead.from_node} → {lead.to_node} (route approximate).",
    ]
    if is_1980_pattern:
        lines.append("Likely cause (not certain): the concrete coating may be breaking off the steel pipe, letting it "
                     "corrode and leak. The same type of pipe from the same plant failed this way in June 1980, when "
                     "daily water loss rose from about 9,000 to about 100,000 gallons before it was found.")
    elif status.kind == "burst":
        lines.append("Likely cause (not certain): the pipe has ruptured. The real cause of the June 2026 break is still "
                     "under investigation, so treat this as a hypothesis.")
    if history:
        lines.append("Past work on this pipe: " + "; ".join(history[-4:]) + ".")
    lines.append(f"Confidence: {status.confidence}. Other candidates: "
                 + ", ".join(f"{s.pipe_id} ({s.reason})" for s in status.top3[1:]) + ".")
    lines.append(f"Next step: confirm with a crew (acoustic listening or a pressure test between the isolation valves). {SIMULATED_LABEL}.")
    return dict(text="\n".join(lines), evidence=status.evidence, pipe_id=lead.pipe_id)


# ------------------------------------------------------------------ work order
def draft_work_order(ds: Dataset, status: LeakStatus) -> dict:
    lead = status.top3[0]
    p = ds.pipe(lead.pipe_id)
    valves = ds.valves[ds.valves.pipe_id == lead.pipe_id].valve_id.tolist()
    burst = status.kind == "burst"
    affected = []
    if lead.from_node.startswith("P") or lead.to_node.startswith("P"):
        affected = ds.buildings[ds.buildings.affected_2026].name.tolist()
    return dict(
        asset_id=lead.pipe_id,
        type="main break repair" if burst else "planned leak repair",
        priority="emergency" if burst else "urgent",
        crew="Utilities pipefitting crew (4), excavation contractor, FP&M utilities engineer on site",
        parts=f"{int(p.diameter_in)}-in repair clamp or replacement spool, coating repair kit, bedding stone",
        valves_to_close=valves,
        steps=[f"Notify the Charter St plant operator and the affected buildings before closing valves {', '.join(valves)}.",
               "Close valves slowly to avoid pressure surges; confirm pressure drop downstream.",
               f"Excavate to {p.depth_ft:g} ft with shoring; confined-space and trench permits required.",
               "Repair, pressure-test, flush, reopen valves slowly, and log the result."],
        safety="Trench over 5 ft needs a protective system (OSHA 1926.652). Chilled water lines may sit near steam lines: verify steam isolation.",
        buildings_at_risk=affected,
        note=("Planned repair while the leak is small avoids an emergency outage." if not burst
              else "Emergency repair. Start the emergency cooling plan in parallel."),
        source=SIMULATED_LABEL,
    )


# ------------------------------------------------------------------ campus alert
def draft_campus_alert(plan: dict) -> dict:
    closed = [b["name"] for b in plan["buildings"] if b["status"] == "closed"]
    rental = [b["name"] for b in plan["buildings"] if b["rental_tons"] > 0 and b["status"] == "open"]
    subject = "Campus cooling update: reduced air conditioning on east campus"
    body = [
        "A chilled-water pipe serving east campus has been shut off for repair. Facilities Planning & Management is "
        "keeping as many buildings cool as possible, with priority for patient care, animal research and labs.",
        "",
        f"Closed until further notice ({len(closed)}): " + (", ".join(closed) if closed else "none") + ".",
        f"Open with temporary chillers ({len(rental)}): " + (", ".join(rental) if rental else "none") + ".",
        "All other affected buildings stay open with reduced cooling; expect warmer rooms in the afternoon.",
        "",
        "If you work in a closed building, check with your supervisor about temporary space. Research staff with "
        "temperature-sensitive equipment should contact their building manager today.",
        "We will update this message daily.",
    ]
    return dict(subject=subject, body="\n".join(body), closed=closed, temp_chillers=rental,
                faq=[("Why is my building closed?", "There is not enough chilled water to keep it below a safe temperature."),
                     ("How long will this last?", "Until the repair is finished; we will post updates daily.")])


# ------------------------------------------------------------------ funding request
def draft_regents_request(ranking: dict) -> str:
    sel = [r for r in ranking["ranking"] if r["selected"]][:8]
    lines = [f"Request: ${ranking['selected_cost_usd'] / 1e6:,.1f}M for {ranking['n_selected']} planned chilled-water pipe replacements.",
             f"Expected avoided losses: ${ranking['selected_benefit_usd'] / 1e6:,.1f}M over 10 years "
             f"(chance of failure × cost of failure, at ${ranking['usd_per_ton_day']:.2f} per ton-day of temporary cooling, from the 2026 event).",
             "Underground utilities are not counted in the ~$2.5B maintenance backlog, yet one failure in June 2026 cost $15.8M.",
             "Top items:"]
    for r in sel:
        lines.append(f"• {r['pipe_id']} ({r['diameter_in']}-in, {r['install_year']}, {r['material']}): {r['risk_label']} — "
                     f"expected loss ${r['expected_loss_usd'] / 1e6:,.2f}M vs replacement ${r['replacement_cost_usd'] / 1e6:,.2f}M.")
    lines.append(f"Method and data: {SIMULATED_LABEL}; network routes are approximate.")
    return "\n".join(lines)


# ------------------------------------------------------------------ Q&A (read-only, cited)
def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9$.]+", s.lower()) if t not in STOP and len(t) > 1]


def _passages(ds: Dataset) -> list[dict]:
    out = []
    for key, text in ds.articles.items():
        title = re.search(r"^TITLE: (.*)$", text, re.M)
        url = re.search(r"^URL: (.*)$", text, re.M)
        body = text.split("\n\n", 1)[-1]
        for para in re.split(r"\n+", body):
            para = para.strip()
            if 80 <= len(para) <= 900:
                out.append(dict(text=para, title=title.group(1) if title else key, url=url.group(1) if url else "", key=key))
    return out


def answer_question(ds: Dataset, question: str, as_of=None) -> dict:
    q = question.strip()
    facts, cites = [], []
    risk = health_scores(ds, as_of=as_of).set_index("asset_id")
    for pid in sorted(set(re.findall(r"CW-[A-Z]\d+[ab]?", q.upper()))):
        if pid in set(ds.pipes.pipe_id):
            p = ds.pipe(pid)
            wo = ds.work_orders[ds.work_orders.asset_id == pid]
            if as_of is not None:
                wo = wo[wo.opened <= pd.Timestamp(as_of)]
            em = wo[wo.priority == "emergency"]
            facts.append(f"{pid}: {int(p.diameter_in)}-inch {p.material}, installed {int(p.install_year)} "
                         f"({2026 - int(p.install_year)} years old), {p.depth_ft:g} ft deep in {p.soil}, "
                         f"{p.from_node} → {p.to_node}, route {p.route_confidence}. Health: {risk.loc[pid, 'label']} "
                         f"(10-year failure chance {risk.loc[pid, 'risk']:.0%}: {risk.loc[pid, 'drivers']}). "
                         f"{len(wo)} work orders, {len(em)} emergencies"
                         + (f", latest emergency {em.opened.max():%Y-%m-%d} ({em.sort_values('opened').iloc[-1].type})." if len(em) else "."))
            cites.append(dict(title="pipe_segments.csv, work_orders.csv (simulated)", url=""))
    names = ds.buildings[["building_id", "name"]]
    hits = names[names.apply(lambda r: r.building_id.lower() in q.lower() or
                             (len(r["name"]) > 6 and r["name"].split(" (")[0].lower() in q.lower()), axis=1)]
    for b in hits.itertuples():
        r = ds.building(b.building_id)
        facts.append(f"{r['name']} ({b.building_id}): {r.use}, ~{int(r.est_gsf):,} sq ft (estimated), "
                     f"design cooling {int(r.design_cooling_tons):,} tons (estimated). In 2026: "
                     f"{'affected, ' + r.status_2026 if r.affected_2026 else 'not affected'}. "
                     f"Safe indoor limit {r.max_indoor_temp_f:.0f} °F" + ("; patient care" if r.patient_care else "")
                     + ("; animal research" if r.animal_research else "") + ".")
        cites.append(dict(title="buildings.csv (public list + estimated loads)", url=""))
    qt = Counter(_tokens(q))
    scored = []
    for p in _passages(ds):
        pt = set(_tokens(p["text"]))
        s = sum(v for t, v in qt.items() if t in pt)
        if s:
            scored.append((s / (1 + len(pt) ** 0.3), p))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    quotes = []
    for _, p in scored:
        if p["key"] in seen:
            continue
        seen.add(p["key"])
        quotes.append(p)
        if len(quotes) == 2:
            break
    for p in quotes:
        facts.append(f"“{p['text'][:400]}{'…' if len(p['text']) > 400 else ''}”")
        cites.append(dict(title=p["title"], url=p["url"]))
    if not facts:
        return dict(answer="I don't have data on that. Try a pipe ID (e.g. CW-M01), a building name, or ask about the 1980 or 2026 events.",
                    citations=[])
    return dict(answer="\n\n".join(facts), citations=cites)


# ------------------------------------------------------------------ agent feed for the replay
AGENTS = {
    "watcher": "Watcher",       # monitoring
    "detective": "Detective",   # diagnosis
    "dispatcher": "Dispatcher", # work orders
    "planner": "Planner",       # emergency cooling plan
    "messenger": "Messenger",   # campus alerts
    "librarian": "Librarian",   # Q&A
}


def agent_feed(ds: Dataset, det, as_of, plan_fn=None) -> list[dict]:
    """What each agent did up to `as_of`, in short plain English. Built from detector output only."""
    t = pd.Timestamp(as_of)
    ev: list[dict] = []

    def add(at, agent, text, level="info"):
        at = pd.Timestamp(at)
        if at <= t:
            ev.append(dict(at=str(at), agent=agent, name=AGENTS[agent], text=text, level=level))

    add("2026-06-01 00:00", "watcher", "Watching 142 sensors across 3 plants and 50 buildings.")
    fa = ds.events.set_index("kind").loc["false_alarm"]
    add(fa.start + pd.Timedelta(hours=1), "watcher", "One pressure sensor dropped, but nothing else changed. Probably a bad sensor. Ignoring it.")

    scan = det.scan(end="2026-06-17 13:00")
    first = scan["first_alert_at"]
    if first:
        s = det.at(first)
        add(first, "watcher", "Charter plant is adding more water than normal, and it keeps rising. Opening a case.", "watch")
        add(pd.Timestamp(first) + pd.Timedelta(minutes=5), "detective",
            f"Top suspect: {s.top3[0].pipe_id}, a 48-inch pipe from 1966. Same kind of pipe failed in 1980.", "watch")
        add(pd.Timestamp(first) + pd.Timedelta(minutes=10), "dispatcher",
            "Drafted a repair order. Waiting for a supervisor to approve.", "watch")
        rate = det.rate
        for gal in (25_000, 60_000):
            hit = rate[(rate.index > pd.Timestamp(first)) & (rate > gal)]
            if len(hit):
                h = hit.index[0]
                add(h, "detective", f"Leak is growing: {det.at(h).excess_gal_per_day:,.0f} extra gallons a day. Still {s.top3[0].pipe_id}.", "act")
    burst = det.burst[det.burst].index
    if len(burst):
        b = burst[0]
        add(b, "watcher", "Pipe burst. Water is pouring out. Shut the valves now.", "act")
        add("2026-06-17 20:00", "watcher", "Valves closed. 34 east-campus buildings now get less cooling.", "act")
        if plan_fn:
            for when, why in (("2026-06-17 20:30", "Cooling plan ready"), ("2026-07-13 00:00", "Heat wave coming. New plan")):
                if pd.Timestamp(when) <= t:
                    p = plan_fn(when)
                    n, closed = p["rented_units"], p["closed"]
                    rent = (f"rent {n} chiller{'s' if n != 1 else ''} (${p['cost_usd_per_day']:,}/day)" if n
                            else "no rented chillers needed while it's mild")
                    add(when, "planner", f"{why}: {rent}, keep {p['kept_open']} buildings open"
                                         + (f", close {closed}." if closed else "."), "watch")
    add("2026-08-10 06:00", "watcher", "Pipe fixed. All buildings back to normal.", "info")
    return sorted(ev, key=lambda e: e["at"])

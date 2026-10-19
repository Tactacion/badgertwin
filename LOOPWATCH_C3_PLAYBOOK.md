# LoopWatch on C3 AI: the zero-to-one playbook

> **Update:** the full app now lives in this repo and runs locally (see README.md). To move it into C3, follow **C3_IMPORT.md**. This playbook is the background reference.

> **What this is:** everything needed to build LoopWatch (a digital twin of UW–Madison's chilled-water network that replays the June 17, 2026 main break) on the C3 Agentic AI Platform using **C3 Code**. The guide covers where every dataset lives, how C3 works, the exact data model, the algorithms, the screens, and a **master prompt you paste into C3 Code** (Part 7).
>
> **Local data folder:** `/Users/revanshphull/c4ai/data/` (built 2026-10-19). Regenerate it any time with `.venv/bin/python scripts/build_twin_data.py`.
>
> **Honesty rule for the whole project:** every public fact is cited. Everything simulated has `data_origin = SIMULATED / ASSUMED / ESTIMATED` in its row and is labelled "simplified, simulated data" on screen.

---

## Contents

1. [The 5-minute version](#1-the-5-minute-version)
2. [How C3 AI works (only what you need)](#2-how-c3-ai-works-only-what-you-need)
3. [Where to find everything (links)](#3-where-to-find-everything)
4. [Your local data, file by file](#4-your-local-data-file-by-file)
5. [The LoopWatch data model (C3 Types)](#5-the-loopwatch-data-model-c3-types)
6. [The algorithms (exact specs)](#6-the-algorithms-exact-specs)
7. [THE MASTER PROMPT: paste into C3 Code](#7-the-master-prompt)
8. [Follow-up prompts, one per phase](#8-follow-up-prompts-one-per-phase)
9. [Screens and design rules](#9-screens-and-design-rules)
10. [Demo script, verification checklist, judge Q&A](#10-demo-script-verification-checklist-judge-qa)
11. [Troubleshooting and fallbacks](#11-troubleshooting-and-fallbacks)
12. [Known gaps and what's not verified](#12-known-gaps-and-whats-not-verified)

---

## 1. The 5-minute version

**The story:** On June 17, 2026, a 4-ft chilled-water main ~20 ft underground near the Charter Street plant broke. 34 buildings lost some or all cooling (23 closed, 11 partially). About 30 rented chillers ran on diesel, and all buildings reopened Aug 10. Total cost was **$15.8M**, of which **~$10M was temporary cooling** and only ~$1.8M was the pipe itself. In June 1980, a 48-inch main from the same plant leaked: water losses rose from ~9,000 to ~100,000 gal/day, and 33 buildings lost AC.

**What you build (one complete path, nothing faked):**

```
sensor data ─▶ Leak detection ─▶ Incident + Diagnosis agent ─▶ Work order (approve)
                                         │
                       burst / capacity drop
                                         ▼
                   Emergency cooling plan (optimizer) ─▶ Approve ─▶ Campus alert draft
```

**What your local data already proves (in simulation):**

| Signal | Value in `data/simulated/` |
|---|---|
| Normal make-up water | ~9,000 gal/day (the 1980 baseline) |
| Leak starts | 2026-06-07 06:00 on pipe **CW-M01** (48-in, 1966, concrete-coated steel, 20 ft deep) |
| Simple detector fires (24-h make-up water > baseline + 4σ) | **2026-06-08 09:00, about 9 days before the burst** |
| Make-up water just before the burst | ~88,000 gal/day (1980 saw ~100,000) |
| Burst | 2026-06-17 14:00, ~4,500 gpm loss; isolated at 20:00 |
| East-zone pressure after isolation | ~89 → ~47 psi; affected buildings get ~70% of their flow and reach ~80 °F indoors |
| Unaffected buildings | no change (control group) |
| Modelled load of the 34 affected buildings | **11,691 tons**, which matches ~30 rented chillers × 300–500 tons (~12,000 tons) |
| Cost model (200,000 Monte Carlo runs) | **$162K/day P50** (P10 $134K, P90 $196K); ~18,000 gal diesel/day; ~184 t CO₂/day |

---

## 2. How C3 AI works (only what you need)

### 2.1 The pieces

| Thing | What it is | Where |
|---|---|---|
| **C3 Agentic AI Platform** | The runtime: a model-driven platform where everything (data, ML, apps, agents) is described as **Types**. | [c3.ai](https://c3.ai/products/c3-agentic-ai-platform/) |
| **C3 AI Studio** | The browser workspace where you build. Your UW workspace lives at `accelerator.c3.ai/uwm/studio/genesis/…` (Okta login). | Your link |
| **C3 Code** | AI app builder inside the platform (GA April 8, 2026). You describe the app in plain English (plus attachments), and it generates **data models (Types), APIs, ML pipelines, agentic workflows and React UI**, then commits them to a Git branch per workspace. | [Overview docs](https://docs.c3.ai/docs/genesis/8.10/topic/c3code-overview) · [Product page](https://c3.ai/products/c3-agentic-ai-platform/c3-code/) · [Announcement](https://c3.ai/c3-ai-announces-c3-code/) |
| **C3 AI Reliability** | Predictive maintenance: sensor + maintenance logs → failure risk and recommended actions. Inspires Tool 2. | [Product](https://c3.ai/products/c3-ai-reliability/) |
| **C3 AI Energy Management** | Energy/emissions forecasting and benchmarking (vendor claims up to 4% cost reduction). Inspires Tool 4 (future work). | [Product](https://c3.ai/products/c3-ai-energy-management/) |
| **C3 Generative AI / Agents** | Agent Gallery in Studio. Workflow agents are nodes + edges (Code Agent, LLM Caller, MCP Agent, Connector, Email, User Input nodes). | [Agents & tools](https://docs.c3.ai/docs/genAiSearch/8.10/topic/genai-dev-agents-and-tools-overview) · [Workflows](https://docs.c3.ai/docs/genAiSearch/8.10/topic/genai-dev-workflows-overview) |

### 2.2 C3 Code workspace: what you'll see

- **Chat panel:** type requests (Enter sends, Shift+Enter adds a new line). Each follow-up builds on the current app, and it also fixes build and runtime errors when you paste them.
- **Three modes:** **Configure** (visual bindings, forms, charts), **Code** (browser VS Code tied to Git), **Preview** (the live app). See the [workspace docs](https://docs.c3.ai/docs/genesis/8.10/topic/c3code-ui-workspace).
- **Attachments:** CSV/XLSX (data), PNG/JPG (mockups), PDF/DOCX/TXT/MD (requirements). Limits are **20 MB per file and 100 MB per message**. Every file in `data/` is under 20 MB (the biggest is 10.2 MB).
- **Deploy:** to Staging or Production. The default quota is 5 workspaces per user.

### 2.3 Core concepts, in one paragraph each

**Types.** Everything is a Type, declared in `.c3typ` files. `entity` = persisted (gets a table). `mixes` pulls in fields and behaviour, `extends` shares the parent's table, and `remix` modifies a type you don't own. Methods are declared on the type and implemented in JS or Python ([docs](https://docs.c3.ai/docs/platform/8.9/topic/type-inheritance)):

```
entity type ShortRangeForecast extends WeatherForecast mixes Evaluatable {
}
extendable entity type WeatherForecast schema name "WTHR" type key "PARENT" {
  precipitation: function(startData: string, endDate: string): double js-server
}
```

**Timeseries.** A *header* type (one per sensor) plus a *data point* type ([docs](https://docs.c3.ai/docs/platform/8.9/topic/ts-types-for-timeseries-data)):

```
entity type SmartBulbMeasurementSeries mixes TimeseriesHeader<SmartBulbMeasurement> schema name "SMRT_BLB_MSRMNT_SRS" {
  smartBulb: SmartBulb
}
@db(datastore="kv", partitionKeyField='parent', persistenceOrder='start', persistDuplicates=false, compactType=true, shortIdReservationRange=100000)
entity type SmartBulbMeasurement mixes IntervalDataPoint<SmartBulbMeasurementSeries> schema name 'SMRT_BLB_MSRMNT' {
  @ts(treatment='avg')  lumens: double
}
```

**Metrics.** Named expressions over timeseries, e.g. `"avg(avg(normalized.data.power))"`, which you evaluate per asset over a time window ([docs](https://docs.c3.ai/docs/platform/8.9/topic/metrics-tsdecl-metrics)). Use them for "daily make-up water", "pressure residual" and so on.

**Data integration.** Raw files land in a `Canonical` type, and a **Transform** maps them onto your entity types ([docs](https://docs.c3.ai/docs/platform/8.9/topic/di-data-map-transform-source)):

```
type CanonicalSensorMeasurement mixes Canonical<CanonicalSensorMeasurement> {
    Timestamp: datetime
    Asset:     string
    Value:     double
}
// metadata/Transform/CanonicalSensorMeasurement-SensorMeasurement.json
{ "name": "CanonicalSensorMeasurement-SensorMeasurement",
  "source": "CanonicalSensorMeasurement", "target": "SensorMeasurement",
  "projection": { "parent": "Asset", "start": "Timestamp", "value": "Value" } }
```

Process one uploaded file with `SourceFile.forId('<id>').process()`. **In practice C3 Code does this for you** when you attach CSVs and ask it to "load these into the data model". Knowing the names helps you read and fix what it generated.

**Packages.** An app is a package with a manifest `<name>.c3pkg.json`, plus `src/` (types and code), `metadata/`, `seed/` (auto-loaded data), `data/` (dev data, loaded with `package.upsertAllSeed()`), `ui/`, `test/` and `gen/` (generated, so don't edit it) ([docs](https://docs.c3.ai/docs/platform/8.9/topic/package-structure-overview)).

**ML.** `MlPipe` and `MlPipeline` wrap sklearn, sktime, keras and similar libraries, and models are registered with `registerMlModel` ([docs](https://docs.c3.ai/docs/platform/8.9/topic/ds-ml-pipes)). For a hackathon, plain Python methods with scikit-learn or numpy are fine. The rubric rewards *working*, not fancy.

**UI.** React components, with React, Redux, RxJS and Webpack preinstalled ([docs](https://docs.c3.ai/docs/uiComponentLibraryReact/8.9/topic/pre-installed-libraries)). C3 Code generates these.

> ⚠️ The syntax above is from the platform **8.9** docs, and C3 Code docs are **8.10**. Let C3 Code generate the real files. Use this section to understand and debug them, not to hand-write everything.

---

## 3. Where to find everything

### 3.1 Already downloaded (in `data/raw/` and `data/curated/`)

| Data | Source (open/download) | Local file |
|---|---|---|
| Hourly Madison weather May 15–Sep 15 2026 (temp, RH, dew point, solar, wind, cloud) | [Open-Meteo Archive API](https://open-meteo.com/en/docs/historical-weather-api), free with no key | `raw/weather_madison_2026_hourly.json` |
| Hourly weather summer 1980 (for the 1980 replay) | Open-Meteo | `raw/weather_madison_1980_hourly.json` |
| Daily weather 2016–2025 (for training "normal") | Open-Meteo | `raw/weather_madison_2016_2025_daily.json` |
| Campus building footprints, names, levels, plants | [OpenStreetMap Overpass API](https://overpass-api.de/) (ODbL) | `raw/osm_campus.json`, `raw/osm_campus_named_buildings.json` |
| UW FP&M facility list (1,108 facilities: number, name, address) | [FP&M](https://fpm.wisc.edu/) | `raw/fpm_facility_list.html` → `curated/uw_buildings.csv` |
| The 34 affected buildings (23 closed / 11 partial) | [Channel 3000](https://www.channel3000.com/news/broken-chilled-water-line-disrupts-cooling-in-34-uw-madison-buildings/article_f4b44405-ccf7-4ace-910a-d938657f595f.html), [UW cooling page](https://news.wisc.edu/campus-cooling-issues/) | `curated/affected_buildings_2026.csv` |
| Incident timeline 1980–2026 | UW News, Cap Times, WMTV, Daily Cardinal | `curated/incident_timeline.csv` |
| Every dollar figure, with quotes | Cap Times, WMTV | `curated/cost_facts.csv` |
| Plants (Charter, Walnut, West Campus Cogen) | [UW Sustainability](https://sustainability.wisc.edu/charter-street-heating-cooling-plant/), [Physical Plant](https://physicalplant.wisc.edu/service-areas/heating-cooling-plants/), [Wikipedia](https://en.wikipedia.org/wiki/West_Campus_Cogeneration_Facility) | `curated/plants.csv` |
| Text snapshots of 15 articles (for the Q&A agent) | Various | `raw/articles/*.txt` |
| Full source list | — | `curated/sources.csv` |
| UW–Madison NIH awards FY2025–26 (1,559 awards, $ by department) | [NIH RePORTER API](https://api.reporter.nih.gov/) | `raw/nih_uwm_awards_fy2025_2026.csv` |
| UW–Madison NSF awards 2023+ (503) | [NSF Award API](https://resources.research.gov/common/webapi/awardapisearch-v1.htm) | `raw/nsf_uwm_awards_2023plus.csv` |
| US weekly diesel price 2024–Oct 2026 | [FRED GASDESW](https://fred.stlouisfed.org/series/GASDESW) (EIA data) | `raw/diesel_us_weekly_fred_GASDESW.csv` |

### 3.2 Generated by the script (in `data/simulated/`)

See Part 4. This is the simplified network, the EPANET replay, the sensors, assets, work orders, chiller sites and the cost model.

### 3.3 Worth getting, but not downloadable

| What | Where to ask/look | Why it matters |
|---|---|---|
| UW **Utility Master Plan** (steam + chilled water, 2005, updated 2015) | FP&M Planning, a [master plans page](https://facilities.fpm.wisc.edu/) request (redacted is fine) | Real pipe routes would replace `route_confidence = approximate` |
| One-page chilled-water loop diagram | FP&M Utilities | Validates the 2-zone model |
| One week of plant meter readings (make-up water, supply flow, ΔP) | FP&M Physical Plant | Real "normal" to train on |
| 20-min interview with an FP&M operator | Physical Plant | Feasibility points on the rubric, and a quote for the pitch |
| UW Sustainability Dashboard (building energy) | [sustainability.wisc.edu](https://sustainability.wisc.edu/) | Real per-building energy for scaling loads |
| NOAA official station data (KMSN) | [NOAA NCEI](https://www.ncei.noaa.gov/cdo-web/), free token | An official weather citation if judges ask |
| EPANET desktop (to view the `.inp`) | [EPA EPANET](https://www.epa.gov/water-research/epanet) | Opens `simulated/badgertwin_network.inp` as a map |

---

## 4. Your local data, file by file

```
data/
├── raw/          # untouched downloads (weather, OSM, NIH, NSF, diesel, articles, FP&M html)
├── curated/      # cleaned public facts (affected buildings, timeline, costs, plants, sources)
└── simulated/    # generated twin: network, EPANET replay, sensors, assets, plan inputs
```

### 4.1 `simulated/`: upload these to C3 Code

| File | Rows | Key columns | Used by |
|---|---|---|---|
| `buildings.csv` | 50 | `building_id, name, use, affected_2026, status_2026, lat, lon, est_gsf, design_cooling_tons, criticality_weight, max_indoor_temp_f, patient_care, animal_research` | Map, planner, priorities |
| `plants.csv` | 3 | `plant_id (P1 Charter, P2 Walnut, P3 WCCF), lat, lon, total_capacity_tons` | Map, planner |
| `chillers.csv` | 12 | `chiller_id, plant_id, capacity_tons, type, install_year, design_kw_per_ton, current_kw_per_ton` | Equipment health |
| `pumps.csv` | 9 | `pump_id, plant_id, hp, install_year, vibration_baseline_ips` | Equipment health |
| `network_nodes.csv` | 65 | `node_id, lat, lon, node_type (plant/hub/building)` | Map |
| `pipe_segments.csv` | 69 | `pipe_id, from_node, to_node, length_ft, diameter_in, role (trunk/crossover/lateral), install_year, material, depth_ft, soil, in_tunnel, route_confidence` | Map, leak localisation, health |
| `valves.csv` | 34 | `valve_id, pipe_id, position, exercised_last` | Work orders ("close V-03, V-04") |
| `sensors.csv` | 142 | `sensor_id, sensor_type, asset_id, unit, description` | Timeseries headers |
| `sensor_readings_hourly.csv` | 257,184 | `timestamp, sensor_id, value` (long format, Jun 1–Aug 15 2026, hourly) | Everything |
| `event_labels.csv` | 4 | ground truth: false alarm Jun 3, slow leak Jun 7→17, burst Jun 17, isolation→Aug 10 | Scoring the detector |
| `work_orders.csv` | 422 | `work_order_id, asset_id, type, priority, opened, closed, cost_usd, preventive` (+ the real 1980 and 2026 events) | Diagnosis agent, health |
| `temp_chiller_sites.csv` | 14 | `site_id, near_building_id, lat, lon, max_units, unit_tons_options, generator_kw_per_unit, setup_cost_usd` | Planner |
| `weather_demand_hourly.csv` | 1,824 | `timestamp, outdoor_temp_f, dew_point_f, campus_load_factor, modelled_campus_demand_tons` | Planner, forecast |
| `research_dollars_by_dept.csv` | 38 | real NIH $ by department type | Criticality evidence |
| `building_research_map.csv` | 10 | assumed building ↔ department mapping + real $ | Criticality evidence |
| `cost_model_summary.csv` / `cost_assumptions.csv` | 4 / 10 | Monte Carlo result and inputs | Plan cost panel |
| `badgertwin_network.inp` | — | EPANET model (open in EPANET or WNTR) | Physics backing |

**Sensor IDs follow a pattern, so prompts can refer to them:**

- `S-MKUP-P1`: Charter make-up water (gal/h). **The leak signal.**
- `S-FLOW-P1..P3`, `S-PRES-P1..P3`, `S-TSUP-P1..P3`: plant flow, pressure and supply temperature.
- `S-PRES-J01..J12`: hub pressures (J01–J07 = east zone fed by Charter; J08–J12 = west zone).
- `S-FLOW-CW-M01a/b`, `S-FLOW-CW-T..`, `S-FLOW-CW-X01/X02`: trunk and crossover flows.
- `S-BFLOW-B001..B050`: building chilled-water flow (gpm). `S-TIN-B001..B050`: indoor temperature (°F).
- Realism: Gaussian noise, ~1% missing readings, and **one injected false alarm** (`S-PRES-J03`, Jun 3 02:00–05:00, −9 psi). The detector must *not* open an incident for it.

### 4.2 How the simulation was built (say this to judges)

1. **Buildings:** the 34 affected buildings (public list) plus 16 unaffected for contrast. Coordinates and footprints come from OSM. GSF = footprint × levels. Design tons = GSF ÷ ft²-per-ton by use (lab 250, clinic 275, animal 230, classroom 375, office 400…).
2. **Network:** two service zones. **East** (the 34 affected) is fed by Charter through the **48-in main CW-M01**. **West** is fed by Walnut + West Campus Cogen. Hubs come from k-means, trunks from a minimum spanning tree plus loop-closing edges, and the zones meet through two **8-in crossovers**. All routes are labelled `approximate`.
3. **Physics:** EPANET via [WNTR](https://usepa.github.io/WNTR/), pressure-driven demand, hourly, Jun 1–Aug 15 2026, with demand driven by real Open-Meteo temperatures and a class-hours occupancy schedule.
4. **Failure:** 1980 pattern. The coating spalls and the leak grows from 0 to ~70 gpm over 10 days, then the main bursts (4,500 gpm) at 14:00 Jun 17. Valves close at 20:00, and the pipe is repaired Aug 10 (the real reopen date).
5. **Realism:** noise, dropouts and one false alarm. Seeded RNG (`1980`), so the dataset is reproducible.

> Note: real Madison weather on Jun 17, 2026 peaked at only ~68 °F, and the hottest hour in the window was **92.4 °F on Jul 14 16:00**. The demo's "95 °F day" is a **what-if forecast override** (judges change it live). Say so.

---

## 5. The LoopWatch data model (C3 Types)

Give this to C3 Code as the intended model. It will generate real `.c3typ` files, and the names matter because agents and UI reference them.

| Type | Kind | Fields (→ = reference) | Loaded from |
|---|---|---|---|
| `Plant` | entity | id, name, lat, lon, totalCapacityTons, chillers → [Chiller] | plants.csv |
| `Chiller` | entity | id, plant → Plant, capacityTons, type, installYear, designKwPerTon, currentKwPerTon | chillers.csv |
| `Pump` | entity | id, plant → Plant, hp, installYear, vibrationBaselineIps | pumps.csv |
| `NetworkNode` | entity | id, lat, lon, nodeType | network_nodes.csv |
| `PipeSegment` | entity | id, fromNode → NetworkNode, toNode → NetworkNode, lengthFt, diameterIn, role, installYear, material, depthFt, soil, inTunnel, routeConfidence | pipe_segments.csv |
| `Valve` | entity | id, pipe → PipeSegment, position, exercisedLast | valves.csv |
| `Building` | entity | id, name, use, affected2026, status2026, lat, lon, estGsf, designCoolingTons, criticalityWeight, maxIndoorTempF, patientCare, animalResearch, node → NetworkNode | buildings.csv |
| `Sensor` | entity, **TimeseriesHeader** | id, sensorType, assetId, unit, description | sensors.csv |
| `SensorReading` | entity, **IntervalDataPoint<Sensor>** | parent → Sensor, start (timestamp), value | sensor_readings_hourly.csv |
| `WeatherHour` | entity | timestamp, outdoorTempF, dewPointF, campusLoadFactor, modelledCampusDemandTons | weather_demand_hourly.csv |
| `WorkOrder` | entity | id, assetId, type, priority, opened, closed, costUsd, preventive, status, approvedBy | work_orders.csv (+ new drafts) |
| `TempChillerSite` | entity | id, nearBuilding → Building, lat, lon, maxUnits, unitTonsOptions, generatorKwPerUnit, setupCostUsd | temp_chiller_sites.csv |
| `Incident` | entity (new) | id, openedAt, kind (leak/burst/capacity), suspectedPipe → PipeSegment, confidence, evidence (json), status (open/diagnosed/planned/closed), diagnosis (text) | created by app |
| `EmergencyPlan` | entity (new) | id, incident → Incident, createdAt, forecastMaxF, allocations (json: building → % cooling / closed), chillerPlacements (json: site → units × tons), costPerDayUsd, dieselGalPerDay, co2TonnesPerDay, status (draft/approved), approvedBy, approvedAt | created by app |
| `CampusAlert` | entity (new) | id, plan → EmergencyPlan, draftText, status, approvedBy | created by app |
| `AuditLog` | entity (new) | id, at, actor, action, objectId, before, after | every approval |
| `CostAssumption` | entity | input, range, basis | cost_assumptions.csv |

**Join rule:** a sensor's `assetId` is a `Plant.id`, `NetworkNode.id` (J01…), `PipeSegment.id` or `Building.id`.

---

## 6. The algorithms (exact specs)

Keep them simple, explainable and running. Each spec says what "done" means.

### 6.1 Tool 1: Leak detection (water balance + pressure residual)

1. **Water balance (primary signal).** `M(t)` = 24-h rolling mean of `S-MKUP-P1` × 24 (gal/day). Baseline = mean and σ over a quiet window (Jun 1–6, excluding the false alarm). Alert when `M(t) > μ + 4σ` for 3 consecutive hours. **Expected: fires about 2026-06-08 09:00.**
2. **Localisation (which pipe).** For each hub `J`, residual `r_J(t)` = pressure − its own same-hour-of-week baseline. Rank pipe segments by the summed residual drop of their two end nodes, weighted by `1 / diameter` age-adjusted. Show the **top 3 suspect segments**. Target: `CW-M01` in the top 3.
3. **False-alarm guard.** A single-sensor pressure drop **without** a water-balance rise is a *sensor fault* and is not opened as an incident. This rule rejects the Jun 3 `S-PRES-J03` glitch.
4. **Output:** `Incident{kind: 'leak', suspectedPipe, confidence, evidence: {gal/day now vs baseline, residuals, chart}}`.
5. **Score it** against `event_labels.csv`: lead time (hours before EV-03), right segment in top 3 (yes/no), and false alarms (count).

### 6.2 Tool 2: Equipment health (simple, live)

Per asset, `risk = 1 − exp(−λ)` with
`λ = base(material) × age_factor(2026 − installYear) × depth_factor × soil_factor × (1 + recent_emergency_WOs)`.
For chillers, add an efficiency drift term `(currentKwPerTon − designKwPerTon) / designKwPerTon`. Show a 0–1 risk, but **label it in words**: "Watch", "Act" or "Normal". `CW-M01` (1966, concrete-coated steel, 20 ft) should rank near the top.

### 6.3 Tool 3: Emergency cooling plan (the centrepiece)

**Inputs:** buildings (tons, weight, max temp, patient care), hourly load factor from `WeatherHour` (or a user-set forecast max °F), the remaining east-zone capacity (crossover flow ÷ 2 gpm/ton ≈ 3,700 tons in the replay), `TempChillerSite` options, and cost assumptions.

**Decision variables (for each building `i`, site `s`, unit size `u`):**
- `x_i ∈ [0,1]`: share of building `i`'s demand served from the plant loop.
- `n_{s,u} ∈ {0,1,2,3}`: number of rented units of size `u` at site `s` (`Σ_u n_{s,u} ≤ maxUnits_s`).
- `c_i ∈ {0,1}`: building `i` closed.

**Objective:** maximise `Σ_i w_i · served_i  −  λ · cost_per_day`, where
`served_i = x_i + (rental tons assigned to i)/L_i`, and
`cost_per_day = Σ n_{s,u} · (rent_u/7 + gen_rent/7 + diesel_gal_per_day_u · price) + Σ setup/expected_days`.

**Constraints:**
- `Σ_i x_i · L_i(t) ≤ PlantCapacityEast(t)` for every hour `t` in the 72-h horizon.
- Rental tons can only serve buildings within ~150 m of a site (from lat/lon).
- `patientCare_i ⇒ served_i = 1`.
- Indoor temperature `T_i(t+1) = T_i(t) + α_i (1 − served_i) L_i(t)/designTons_i − β (T_i − 72)` stays at or below `maxIndoorTempF_i`, otherwise `c_i = 1` (closed, which costs `w_i`).
- **Pre-cooling:** allow `x_i` to be higher overnight to bank coolth (optional stretch goal).

**Solver:** `scipy.optimize.milp` (or `pulp` if available) in a Python method. **Fallback:** a greedy rule that sorts by `w_i / tons`, fills plant capacity, then places rentals at the highest-weight unmet buildings. It runs in milliseconds, so the demo never breaks.

**Output:** an `EmergencyPlan` with a building table (served % / closed), site placements, cost/day, diesel/day and CO₂/day, plus a **plain-language summary from the LLM**. Show cost next to UW's actual ~$156K–$233K/day for comparison.

### 6.4 Tool 5: Repair priorities (simple, live)

`expected_loss_i = risk_i × consequence_i`, where `consequence = Σ (downstream building tons × criticality weight × $/ton-day × expected outage days) + repair cost`. A segment's downstream buildings are found by graph search from `PipeSegment` toward the buildings it feeds. Rank, then knapsack-select the set of repairs within a budget slider (default $50M). The LLM drafts a one-page Regents request with the evidence.

### 6.5 The agents (each a C3 workflow/agent; humans approve)

| Agent | Trigger | Does | Approver |
|---|---|---|---|
| Monitoring | Tool 1 alert or risk > threshold | Opens `Incident`, notifies the on-call operator | — |
| Diagnosis | Incident opened | Pulls sensor history, pipe attributes and work orders (incl. WO-H1980), then explains the likely cause **with evidence links** | — |
| Work order | Diagnosis confirmed | Drafts a `WorkOrder`: crew, parts, **valves to close** (from `valves.csv` on the suspect pipe), safety notes | Shift supervisor |
| Emergency planning | Burst / capacity < demand | Runs Tool 3 and re-runs on forecast change | FP&M director + VC Finance |
| Campus alerts | Plan approved | Drafts email, building list and FAQ text from the plan | Communications |
| Q&A | Any question | Answers from `raw/articles/*.txt`, pipe/asset tables and work orders, **with citations** | read-only |

(Funding request = Tool 5 output, run quarterly, approved by Capital Planning. Show it but keep it simple.)

---

## 7. THE MASTER PROMPT

**How to use it:**

1. Open your C3 Code workspace.
2. Attach **all files from `data/simulated/`** except the `.inp` (about 10.6 MB total, every file under 20 MB). Also attach `curated/affected_buildings_2026.csv`, `curated/incident_timeline.csv`, `curated/cost_facts.csv`, `curated/sources.csv` and the 15 files in `raw/articles/`. If one message rejects that many files, send the CSVs first and the articles in a second message, saying "more context for the Q&A agent".
3. Paste everything in the box below and send.
4. Then go phase by phase with Part 8. **Don't expect one message to build everything.** The master prompt sets the spec, and the phase prompts get each piece working.

````text
You are building "LoopWatch", a working app on the C3 Agentic AI Platform: a simplified digital twin of
UW–Madison's campus chilled-water network that replays the June 17, 2026 chilled-water main break and shows
how earlier detection and an optimized emergency plan would change the outcome. This is for a judged
hackathon; the rubric rewards a COMPLETE, WORKING end-to-end path over many half-built features. Nothing on
screen may be fake or static: every number must come from the data model or a running computation.

## Context (real, public facts — cite them in the UI where shown)
- 2026-06-17: a 4-ft chilled-water main ~20 ft underground near the Charter Street plant broke. 34 buildings
  lost cooling (23 closed, 11 partially). ~30 rented chillers on diesel generators. All reopened 2026-08-10.
- Total cost $15.8M (Cap Times, Oct 8 2026): ~$10.0M temporary chillers, ~$4.0M additional pipe damage,
  ~$1.8M pipe repair. Regents moved $40M to the related Engineering Drive utilities project.
- June 1980: a 48-inch main from the same plant leaked; daily water loss rose from ~9,000 to ~100,000 gal;
  33 buildings lost central AC. It was found by reading meters (missing water).
- Facts and sources are in the attached curated_*.csv / sources.csv and article .txt files.

## Attached data (load ALL of it into the data model; keep the data_origin column everywhere)
The network, sensors and assets are SIMULATED from public facts. Every screen that shows them must carry a
small grey label: "Simplified, simulated data built from public facts".
- buildings.csv (50): building_id, name, use, affected_2026, status_2026, lat, lon, est_gsf,
  design_cooling_tons, criticality_weight, max_indoor_temp_f, patient_care, animal_research, data_origin
- plants.csv (3): P1 Charter St, P2 Walnut St, P3 West Campus Cogeneration
- chillers.csv, pumps.csv, valves.csv
- network_nodes.csv (plants P1-P3, hubs J01-J12, buildings B001-B050 with lat/lon)
- pipe_segments.csv (69): pipe_id, from_node, to_node, length_ft, diameter_in, role(trunk/crossover/lateral),
  install_year, material, depth_ft, soil, in_tunnel, route_confidence. CW-M01 is the 48-in Charter main.
  J01-J07 = east zone (fed by Charter via CW-M01), J08-J12 = west zone; CW-X01/CW-X02 are 8-in crossovers.
- sensors.csv (142 sensors) + sensor_readings_hourly.csv (257,184 rows; long format timestamp,sensor_id,value;
  2026-06-01..2026-08-15 hourly). Key sensor: S-MKUP-P1 = Charter make-up water in gal/h (the leak signal).
  S-PRES-Jxx hub pressure psi; S-FLOW-* gpm; S-BFLOW-Bxxx building flow gpm; S-TIN-Bxxx indoor temp °F.
  Contains noise, ~1% missing values and one deliberate false alarm (S-PRES-J03, 2026-06-03 02:00-05:00).
- event_labels.csv: ground truth (false alarm, slow leak 06-07→06-17, burst 06-17 14:00, isolation→08-10).
- weather_demand_hourly.csv: real hourly Madison temps + campus load factor.
- work_orders.csv (422, includes real WO-H1980 and WO-H2026 on CW-M01).
- temp_chiller_sites.csv (14 candidate rental-chiller sites), cost_assumptions.csv, cost_model_summary.csv.
- research_dollars_by_dept.csv / building_research_map.csv (real NIH $; building mapping assumed).

## Data model (create these Types; use these names)
Plant, Chiller, Pump, NetworkNode, PipeSegment (from/to → NetworkNode), Valve (→ PipeSegment),
Building (→ NetworkNode), Sensor as a timeseries header and SensorReading as its interval data points
(value: double, start: datetime), WeatherHour, WorkOrder, TempChillerSite (→ Building), CostAssumption,
plus new entities the app writes: Incident, EmergencyPlan, CampusAlert, AuditLog.
Incident: openedAt, kind(leak|burst|capacity), suspectedPipe → PipeSegment, top3 (json), confidence,
evidence (json), diagnosis (text), status(open|diagnosed|planned|closed).
EmergencyPlan: incident → Incident, createdAt, forecastMaxF, allocations json (building → served %, closed),
chillerPlacements json (site → units × tons), costPerDayUsd, dieselGalPerDay, co2TonnesPerDay,
summary (text), status(draft|approved), approvedBy, approvedAt.
AuditLog: at, actor, action, objectId, before, after — written on every approve/edit.

## Computations (implement as Python methods on the Types; deterministic and fast)
1. detectLeak(asOf): 24-h rolling make-up water (gal/day) from S-MKUP-P1 vs baseline mean+4σ from
   2026-06-01..06-06; alert after 3 consecutive hours above. Localise: per hub, pressure residual vs its own
   hour-of-week baseline; score each trunk pipe by the residual drop at its two end nodes; return top 3.
   A pressure drop at ONE sensor without a water-balance rise = sensor fault, not an incident (must reject
   the 06-03 J03 glitch). Expected: alert ~2026-06-08 09:00, CW-M01 in top 3.
2. healthScore(asset): risk = 1 - exp(-λ), λ from age (2026-install_year), material (concrete-coated steel
   worst), depth, soil, and count of emergency work orders; chillers add (current_kw_per_ton/design - 1).
   Show as words: Normal / Watch / Act.
3. planEmergency(incident, forecastMaxF, budgetPerDayUsd, extraChillerOutageTons=0): mixed-integer program
   (scipy.optimize.milp; if unavailable use the greedy fallback below) over a 72-hour horizon:
   maximize Σ criticality_weight·served_share − λ·cost_per_day subject to
   - plant cooling delivered to east-zone buildings ≤ remaining east capacity each hour (after CW-M01 is
     isolated: crossover flow ÷ 2 gpm/ton ≈ 3,700 tons; minus extraChillerOutageTons),
   - building load each hour = design_cooling_tons × campus_load_factor scaled to forecastMaxF,
   - rental units: 300/400/500-ton options, ≤ max_units per site, a site serves buildings within 150 m,
   - patient_care buildings always 100% served,
   - indoor temp model T(t+1)=T(t)+α(1-served)·load/design − β(T−72) ≤ max_indoor_temp_f else closed,
   - cost/day = units × (rent/7 + generator rent/7 + diesel gal/day × $/gal) using cost_assumptions.
   Greedy fallback: sort by weight/ton, fill plant capacity, place rentals at highest-weight unmet buildings.
   Return the plan, and compare cost/day with UW's actual ~$156K–$233K/day.
4. rankRepairs(budgetUsd=50e6): expected_loss = risk × consequence (downstream building tons × weight ×
   outage days + repair cost); knapsack within budget; return ranked list with evidence.

## Agents (C3 agents/workflows; agents SUGGEST, named humans APPROVE anything that moves a valve, spends
money or messages campus; every approval writes AuditLog)
- Monitoring: when detectLeak or healthScore crosses threshold → create Incident, notify on-call operator.
- Diagnosis: explain likely cause in plain language using sensor history, pipe attributes (CW-M01: 1966,
  concrete-coated steel, 20 ft deep) and work orders incl. WO-H1980; show evidence links. Never claim
  certainty; the real 2026 cause is still under investigation.
- Work order: draft WorkOrder with crew, parts, valves to close (from Valve on the suspect pipe), safety notes.
  Approver: Shift supervisor.
- Emergency planning: run planEmergency; re-run when forecast or outage inputs change.
  Approver: FP&M director + VC Finance.
- Campus alerts: draft email + building list + FAQ from the approved plan. Approver: Communications.
- Q&A: answer questions about any pipe, building or the incident history from the data and attached
  articles, ALWAYS with citations; read-only.

## UI — three screens for one user: the FP&M operator on call. One primary button per screen.
Design rules: plain language not scores ("Likely leak on CW-M01 between J02 and Charter plant", not
"anomaly 0.93"); every number shows its unit and source; color ONLY means risk (grey normal, amber watch,
red act); cost and diesel/day next to every plan; suggest-then-approve, every suggestion editable.
1. "Campus" — map of plants, pipes (width by diameter), 50 buildings colored by risk; a REPLAY time slider
   (2026-06-01..2026-08-15) with play/fast-forward that drives every widget; a make-up water chart with the
   baseline band; Q&A box. Primary button: "Open incident" (enabled when an alert exists).
2. "Incident" — the alert, top-3 suspect pipes on the map, diagnosis text with evidence, drafted work order
   with valve list. Primary button: "Approve work order".
3. "Emergency plan" — inputs: forecast max °F (default from data, judge can set 95), extra chiller outage
   (tons), budget/day. Outputs: building table (served % / closed, why), chiller placements on the map,
   cost/day, diesel/day, CO2/day, plain-language summary, comparison to UW's actual ~$156K–$233K/day.
   Primary button: "Approve plan" → creates CampusAlert draft for approval.
Every screen footer: "Simplified, simulated data built from public facts" + link to Sources page.

## Build order (do this first, then stop and show me)
Phase 1: Types + load every CSV + a Data Health page showing row counts per Type and a sample chart of
S-MKUP-P1. Do not build UI beyond that yet. After Phase 1, list what you created and any load errors.
````

---

## 8. Follow-up prompts, one per phase

Send them one at a time. After each one, open **Preview**, check the "Done when" line, and only then move on. If something breaks, paste the exact error back into chat with "fix this".

**Phase 2: Leak detection**

```text
Implement detectLeak(asOf) exactly as specified. Add a page "Detector test" that runs it hour by hour over
2026-06-01..2026-06-20 and shows: first alert time, hours of warning before the 2026-06-17 14:00 burst,
top-3 suspect pipes, and whether the 2026-06-03 J03 glitch was rejected, scored against EventLabel.
```

*Done when:* the alert is about 06-08 09:00 (~220 h warning), CW-M01 is in the top 3, and there are 0 false alarms.

**Phase 3: Campus screen + replay**

```text
Build screen 1 "Campus": map (plants, pipes sized by diameter, buildings colored Normal/Watch/Act from
healthScore and live sensor state at the replay time), replay slider with play and 10x/100x, make-up water
chart with baseline band, Q&A box wired to the Q&A agent. "Open incident" button enabled when detectLeak
has an alert at the current replay time; clicking it creates the Incident.
```

*Done when:* dragging to Jun 9 turns CW-M01 amber or red and enables the button.

**Phase 4: Incident + agents**

```text
Build screen 2 "Incident": show the Incident, top-3 suspects on the map, run the Diagnosis agent (plain
language, cites sensor charts, pipe attributes and WO-H1980), and the Work order agent drafting a WorkOrder
with crew, parts, valves to close and safety notes. "Approve work order" requires entering approver name;
write AuditLog. Make the draft editable before approval.
```

*Done when:* an approved work order appears in `WorkOrder` with `approvedBy`, and an audit row exists.

**Phase 5: Emergency plan**

```text
Build screen 3 "Emergency plan" and planEmergency (MILP with greedy fallback, show which solver ran and
runtime). Default scenario: replay time 2026-06-17 20:00 after isolation. Inputs: forecast max °F (try 95),
extra chiller outage tons, budget/day. Re-solve live on change (<5 s). Show building table, placements on map,
cost/day, diesel gal/day, CO2 t/day, LLM summary, and UW actual ~$156K–$233K/day for comparison.
"Approve plan" → EmergencyPlan.status=approved + AuditLog + Campus alerts agent drafts the CampusAlert.
```

*Done when:* changing 80 °F → 95 °F changes the plan and cost, patient-care buildings are always 100% served, and approval produces an alert draft.

**Phase 6: Repair priorities + Sources page**

```text
Add rankRepairs with a budget slider ($10M–$100M, default $50M) and a one-page Regents request drafted by
the LLM with evidence. Add a Sources page listing sources.csv with links, and the data_origin legend.
```

**Phase 7: Polish + guardrails**

```text
Audit every screen against the design rules: units on every number, color only for risk, one primary
button, simulated-data label, no placeholder or hard-coded numbers. List anything that is static and make
it computed. Add a "Reset demo" button that clears Incidents/Plans/Alerts created during the session.
```

---

## 9. Screens and design rules

```
┌ CAMPUS ───────────────────────────────────────── Replay: Jun 09 2026 08:00 ▶ 10x ┐
│  [map: P1 P2 P3 · pipes · 50 buildings]        │ Make-up water (gal/day)           │
│   CW-M01 ███ (red)                             │  ▁▁▁▁▂▃▅▇  ← baseline band        │
│                                                │ "Charter is losing ~3,500 gal/day │
│                                                │  more than normal since Jun 8."   │
│  Ask: "How old is CW-M01 and what failed near it?"                                │
│                                     [ Open incident ]   simulated data from public facts │
└───────────────────────────────────────────────────────────────────────────────────┘
```

- **One user:** the FP&M operator on call. Approvers see the same screens with Approve enabled.
- **Plain words:** "Likely leak on CW-M01 (Charter main, 1966) — 2 of 3 signals agree."
- **Color = risk only:** grey normal, amber watch, red act.
- **Every plan shows cost/day + diesel/day.** Nothing executes without a named approver.
- **Usability test** before demo day: 3 people, 3 tasks (find the leak · approve the work order · keep patient care and animal research cool within budget). Time each, fix the top 3 confusions.

---

## 10. Demo script, verification checklist, judge Q&A

### 5-minute script

| Time | Beat | On screen |
|---|---|---|
| 0:00 | "$15.8M. And it happened in 1980 too." | 1980 and 2026 headlines from `incident_timeline.csv` |
| 0:30 | The campus twin | Campus screen. Ask Q&A: "How old is CW-M01?" (answer cites sources) |
| 1:15 | Nine days early | Replay to Jun 8. Make-up water leaves its band, CW-M01 turns red. Open incident, see the diagnosis, approve the work order. "Planned repair, not an emergency." |
| 2:15 | What if nobody acts | Jump to Jun 17 20:00. Plan solves in seconds and shows cost/day vs UW's $156K–$233K. **A judge sets 95 °F and knocks out a chiller**, and the plan updates live. |
| 3:15 | The money | Repair priorities. Underground utilities aren't in the $2.5B backlog. One-page Regents request. |
| 4:00 | Scale + close | 13 UW campuses next. "The pipe warned us in 1980. LoopWatch makes sure we notice next time." |

### Verification checklist (run the night before)

- [ ] All 17 CSVs loaded, and Data Health row counts match Part 4.1.
- [ ] Detector: first alert about Jun 8, CW-M01 in top 3, Jun 3 glitch rejected.
- [ ] Incident → diagnosis → work order → approve → AuditLog row.
- [ ] Plan re-solves in under 5 s when °F, outage or budget changes. Patient care is always 100%.
- [ ] Plan approve → CampusAlert draft → approve.
- [ ] Every screen has the simulated-data label, and no hard-coded numbers remain.
- [ ] Backup screen recording of the full replay.
- [ ] Reset demo button works.

### Judge Q&A, short answers

| Q | A |
|---|---|
| Is the data real? | Public facts are real and cited. Network and sensors are simulated from them (EPANET physics) and labelled on screen. |
| How did you get the pipe network? | Plant and building locations are public (OSM, UW). Routes are approximate, two service zones, labelled. We've asked FP&M for the Utility Master Plan. |
| Would this have prevented June 17? | The cause is still under investigation, so we don't claim that. We claim earlier warning for 1980-style slow leaks and a cheaper response to any failure. |
| Why trust the load model? | The affected buildings sum to ~11,700 design tons, consistent with ~30 rented chillers at 300–500 tons. |
| Is it safe to let AI run a utility? | It doesn't. It only reads data, agents suggest, named people approve, and everything is audited. |
| Isn't this just C3 AI Reliability? | Reliability is one piece. What's new is the emergency cooling optimizer, weighting buildings by what's at stake, and the 1980/2026 replay. |

---

## 11. Troubleshooting and fallbacks

| Problem | Fix |
|---|---|
| Upload rejected | Each file must be ≤ 20 MB and each message ≤ 100 MB. `sensor_readings_hourly.csv` is 10.2 MB. If needed, split it by month with `.venv/bin/python -c "import pandas as pd; d=pd.read_csv('data/simulated/sensor_readings_hourly.csv'); [g.to_csv(f'data/simulated/readings_{m}.csv',index=False) for m,g in d.groupby(d.timestamp.str[:7])]"` |
| C3 Code builds too much at once | Re-send: "Stop. Only do Phase N. Show me what exists." |
| Timeseries load errors | Ask: "Load sensor_readings_hourly.csv as SensorReading data points with parent = Sensor(sensor_id), start = timestamp, value = value; skip empty values." |
| `scipy.optimize.milp` not available | Ask for the greedy fallback and display "solver: greedy". It's honest and fast. |
| LLM agent hallucinates numbers | Instruct: "The agent may only state numbers returned by tool calls; cite the source table/row." |
| Map component missing | Ask for a lat/lon scatter (SVG or canvas) with lines for pipes. A real basemap isn't required. |
| Need to change the scenario | Edit constants at the top of `scripts/build_twin_data.py` (`LEAK_START`, `BURST`, crossover size) and re-run. Outputs are reproducible (seed 1980). |
| WNTR crashes on macOS (exit 137) | Re-sign its native libraries: `for f in $(find .venv/lib/python3.14/site-packages/wntr -name "*.dylib" -o -name "*.so"); do codesign -s - -f "$f"; done` |

---

## 12. Known gaps and what's not verified

- **The pipe network is not UW's.** Real routes, sizes and valves aren't public.
- **Plant capacities per chiller are assumed.** Only Charter's 8,000- and 8,500-ton YORK units are public, plus ">50,000 tons" campus total. West Campus tonnage (20,000→30,000) is from a search snippet only.
- **1980 details** (48-in, 9,000→100,000 gal/day, 33 buildings) come from a UW release snippet, because the full page is login-restricted (`verified=false` in the curated files).
- **Building uses** for some affected buildings are inferred from names, and 11 UW building-number matches are low-confidence (see `match_confidence`).
- **Not found:** the "$33.47M Lakeshore project" and a Feb 2019 Engineering Centers flood. Don't cite them. The $2.5B backlog figure conflicts with older $1.5B figures.
- **Not verified:** the judging rubric (confirm it with organizers), the exact C3 8.10 `.c3typ` syntax, and whether your accelerator workspace has scipy available.
- **C3 vendor claims** (e.g. "up to 100x productivity", the C3 Code benchmark) are C3's own and not independent.

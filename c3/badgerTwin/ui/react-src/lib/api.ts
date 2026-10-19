// Typed client for the BadgerTwin API (badgertwin/server.py).
export type Risk = "Normal" | "Watch" | "Act" | "Closed"

export interface Suspect { pipe_id: string; from_node: string; to_node: string; score: number; flow_imbalance_gpm: number | null; reason: string }
export interface LeakStatus {
  as_of: string; alert: boolean; kind: "normal" | "leak" | "burst" | "isolated"
  makeup_gal_per_day: number; baseline_gal_per_day: number; threshold_gal_per_day: number; excess_gal_per_day: number
  first_alert_at: string | null; hours_alerting: number; confidence: string; headline: string
  top3: Suspect[]; evidence: string[]
}
export interface PipeState { pipe_id: string; label: Risk; health: Risk; risk: number; flow_gpm: number; velocity_fps: number; forward: boolean }
export interface BuildingState { building_id: string; label: Risk; indoor_f: number | null; flow_gpm: number | null }
export interface Incident { id: string; kind: string; suspected_pipe: string; top3: Suspect[]; confidence: string; headline: string; evidence: string[]; diagnosis: string; status: string; replay_time: string }
export interface State {
  t: string; leak: LeakStatus; pipes: PipeState[]; buildings: BuildingState[]
  makeup: { timestamp: string; gal_per_day: number | null }[]; outdoor_f: number | null; open_incidents: Incident[]
}
export interface Meta { label: string; replay_start: string; replay_end: string; burst: string; isolated: string }
export interface Feature<P, G = { type: string; coordinates: any }> { type: "Feature"; id?: number; geometry: G; properties: P }
export interface FC<P> { type: "FeatureCollection"; features: Feature<P>[] }
export interface Geo {
  buildings: FC<{ building_id: string; name: string; use: string; affected: boolean; status_2026: string; tons: number; height: number }>
  pipes: FC<{ pipe_id: string; diameter: number; role: string; install_year: number; material: string }>
  plants: FC<{ plant_id: string; name: string }>
  hubs: FC<{ node_id: string }>
}
export interface FeedItem { at: string; agent: string; name: string; text: string; level: "info" | "watch" | "act"; live?: boolean }
export interface WorkOrder { id: string; status: string; approved_by: string | null; type: string; priority: string; crew: string; parts: string; valves_to_close: string[]; steps: string[]; safety: string; note: string }
export interface PlanBuilding { building_id: string; name: string; use: string; weight: number; need_tons: number; plant_tons: number; rental_tons: number; served_pct: number; status: "open" | "closed"; peak_indoor_f: number | null; max_indoor_f: number; why: string }
export interface Placement { site_id: string; lat: number; lon: number; near: string; units: number; unit_tons: number; usd_per_day: number }
export interface Plan {
  id?: string; solver: string; solve_ms: number; plant_capacity_tons: number; peak_hour: string; peak_outdoor_f: number; east_demand_tons: number
  buildings: PlanBuilding[]; placements: Placement[]; cost_usd_per_day: number; diesel_gal_per_day: number; co2_t_per_day: number
  rented_units: number; rented_tons: number; kept_open: number; closed: number; uw_actual_usd_per_day: [number, number]; summary: string
}
export interface Alert { id: string; subject: string; body: string; status: string; approved_by: string | null }
export interface RepairRow { pipe_id: string; role: string; diameter_in: number; install_year: number; material: string; risk: number; risk_label: Risk; expected_loss_usd: number; replacement_cost_usd: number; selected: boolean }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = (data as any).detail
    throw new Error(Array.isArray(d) ? d.map((x: any) => x.msg).join("; ") : d || res.statusText)
  }
  return data as T
}

export const api = {
  meta: () => call<Meta>("/api/meta"),
  geo: () => call<Geo>("/api/geo"),
  state: (t: string) => call<State>(`/api/state?t=${encodeURIComponent(t)}`),
  agents: (t: string) => call<{ feed: FeedItem[] }>(`/api/agents?t=${encodeURIComponent(t)}`),
  openIncident: (t: string) => call<{ incident: Incident; work_order?: WorkOrder }>("/api/incidents", { t }),
  incident: (id: string) => call<{ incident: Incident; work_orders: WorkOrder[] }>(`/api/incidents/${id}`),
  approveWorkOrder: (id: string, approver: string, edits: Partial<WorkOrder> | null) => call<WorkOrder>(`/api/work-orders/${id}/approve`, { approver, edits }),
  plan: (body: Record<string, unknown>) => call<Plan>("/api/plan", body),
  approvePlan: (id: string, approvers: Record<string, string>) => call<{ plan: Plan & { approvals: Record<string, { name: string }> }; missing: string[]; alert?: Alert }>(`/api/plans/${id}/approve`, { approvers }),
  approveAlert: (id: string, approver: string, body: string) => call<Alert>(`/api/alerts/${id}/approve`, { approver, body }),
  repairs: (budget: number) => call<{ ranking: RepairRow[]; request: string; selected_cost_usd: number; selected_benefit_usd: number; n_selected: number }>(`/api/repairs?budget_usd=${budget}`),
  ask: (question: string, t: string) => call<{ answer: string; citations: { title: string; url: string }[] }>("/api/ask", { question, t }),
  sources: () => call<{ sources: { url: string; title: string; publisher: string; date: string; what_it_supports: string }[] }>("/api/sources"),
  audit: () => call<{ audit: { at: string; actor: string; action: string; object_id: string }[] }>("/api/audit"),
  reset: () => call<{ ok: boolean }>("/api/reset", {}),
}

export const fmt = (n: number | null | undefined, d = 0) =>
  n === null || n === undefined || Number.isNaN(n) ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })
export const money = (n: number) => "$" + fmt(n)
export const niceTime = (t: string) =>
  new Date(t.replace(" ", "T")).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" })

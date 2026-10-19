import { useEffect, useMemo, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { Area, AreaChart, ReferenceLine, XAxis, YAxis } from "recharts"
import { toast } from "sonner"
import { CheckCircle2, Pencil, Wrench } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ChartContainer } from "@/components/ui/chart"
import { api, fmt, money, type Alert, type Incident, type Plan, type RepairRow, type State, type WorkOrder } from "@/lib/api"
import { cn } from "@/lib/utils"
import { CountUp, Glass, Pulse, riskDot, Stat } from "./bits"

// ============================================================================ LIVE STATUS
const KIND = {
  normal: { word: "All normal", tone: "text-white", ring: "", dot: "bg-emerald-400" },
  leak: { word: "Leak found", tone: "text-amber-300", ring: "shadow-[0_0_0_1px_rgba(245,165,36,0.35),0_0_50px_-12px_rgba(245,165,36,0.6)]", dot: "bg-amber-400" },
  burst: { word: "Pipe burst", tone: "text-red-400", ring: "shadow-[0_0_0_1px_rgba(255,77,79,0.4),0_0_60px_-10px_rgba(255,77,79,0.7)]", dot: "bg-red-500" },
  isolated: { word: "Cooling cut", tone: "text-amber-300", ring: "shadow-[0_0_0_1px_rgba(245,165,36,0.35),0_0_50px_-12px_rgba(245,165,36,0.6)]", dot: "bg-amber-400" },
}

export function StatusPanel({ state, onOpen, hasCase }: { state: State; onOpen: () => void; hasCase: boolean }) {
  const k = KIND[state.leak.kind]
  const data = useMemo(() => state.makeup.filter((d) => d.gal_per_day !== null).map((d) => ({ t: d.timestamp.slice(5, 10), v: Math.min(d.gal_per_day!, 140000) })), [state.makeup])
  const lost = state.leak.excess_gal_per_day
  return (
    <Glass className={cn("w-[340px] p-5 transition-shadow duration-700", k.ring)}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
        {state.leak.kind === "normal" ? <span className={cn("size-2.5 rounded-full", k.dot)} /> : <Pulse color={k.dot} />} Campus cooling
      </div>
      <AnimatePresence mode="wait">
        <motion.div key={state.leak.kind} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.35 }}>
          <div className={cn("mt-2 text-3xl font-semibold", k.tone)}>{k.word}</div>
          <p className="mt-1 text-[13px] leading-snug text-white/70">{shortLine(state)}</p>
        </motion.div>
      </AnimatePresence>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label="Water added today"><CountUp value={state.leak.makeup_gal_per_day || 0} suffix=" gal" /></Stat>
        <Stat label="Above normal"><CountUp value={lost} suffix=" gal" className={lost > 2000 ? "text-amber-300" : ""} /></Stat>
      </div>
      <ChartContainer config={{ v: { label: "Water added", color: "#7dd3fc" } }} className="mt-3 h-24 w-full">
        <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={state.leak.alert ? "#ff4d4f" : "#7dd3fc"} stopOpacity={0.55} /><stop offset="100%" stopColor="#7dd3fc" stopOpacity={0} /></linearGradient>
          </defs>
          <XAxis dataKey="t" hide /><YAxis hide domain={[0, "dataMax"]} />
          <ReferenceLine y={state.leak.threshold_gal_per_day} stroke="rgba(255,255,255,0.35)" strokeDasharray="4 4" />
          <Area dataKey="v" type="monotone" stroke={state.leak.alert ? "#ff6b6b" : "#7dd3fc"} strokeWidth={2} fill="url(#g)" isAnimationActive={false} />
        </AreaChart>
      </ChartContainer>
      <div className="mt-1 text-[11px] text-white/40">Last 14 days · dashed line = alarm level</div>
      {(state.leak.alert || hasCase) && (
        <Button onClick={onOpen} className="mt-4 h-11 w-full rounded-xl bg-white text-black hover:bg-white/90">{hasCase ? "Open the case" : "Start a case"}</Button>
      )}
    </Glass>
  )
}

function shortLine(s: State) {
  const top = s.leak.top3[0]?.pipe_id
  switch (s.leak.kind) {
    case "normal": return "Water in, water out. Nothing missing."
    case "leak": return `Water is going missing. Most likely from pipe ${top}.`
    case "burst": return `Pipe ${top} broke. Water is pouring out.`
    case "isolated": return "The broken pipe is shut off. East campus gets less cooling."
  }
}

// ============================================================================ INCIDENT
export function IncidentPanel({ incidentId }: { incidentId: string | null }) {
  const [inc, setInc] = useState<Incident | null>(null)
  const [wo, setWo] = useState<WorkOrder | null>(null)
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState("")
  const [draft, setDraft] = useState<Partial<WorkOrder>>({})
  useEffect(() => {
    if (!incidentId) return
    api.incident(incidentId).then((r) => { setInc(r.incident); const w = r.work_orders.at(-1) ?? null; setWo(w); setDraft(w ?? {}) })
  }, [incidentId])
  if (!incidentId || !inc) return <Glass className="w-[400px] p-6 text-white/60">No open case yet. Play the timeline until the Watcher spots something.</Glass>

  async function approve() {
    if (!wo) return
    const edits = Object.fromEntries(Object.entries(draft).filter(([k, v]) => ["crew", "parts", "valves_to_close", "priority"].includes(k) && JSON.stringify(v) !== JSON.stringify((wo as any)[k])))
    try { const w = await api.approveWorkOrder(wo.id, name, Object.keys(edits).length ? edits : null); setWo(w); setEdit(false); toast.success(`Approved by ${w.approved_by}. Crew can go.`) }
    catch (e: any) { toast.error(e.message) }
  }
  const max = Math.max(...inc.top3.map((s) => s.score), 0.01)
  const why = inc.diagnosis.split("\n").find((l) => l.startsWith("Likely cause"))?.replace("Likely cause (not certain): ", "")
  return (
    <Glass className="flex max-h-[calc(100vh-220px)] w-[420px] flex-col overflow-y-auto p-5">
      <div className="text-xs uppercase tracking-wider text-white/45">Case {inc.id}</div>
      <div className="mt-1 text-2xl font-semibold">{inc.kind === "burst" ? "Burst on " : "Leak on "}{inc.suspected_pipe}</div>
      <p className="mt-1 text-[13px] text-white/65">Found {inc.replay_time.slice(5, 16).replace("-", "/")} · confidence {inc.confidence}</p>

      <div className="mt-5 space-y-2.5">
        {inc.top3.map((s, i) => (
          <div key={s.pipe_id}>
            <div className="flex justify-between text-[13px]"><span className={i === 0 ? "font-semibold" : "text-white/70"}>{i + 1}. {s.pipe_id}</span><span className="text-white/45">{s.from_node} → {s.to_node}</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
              <motion.div initial={{ width: 0 }} animate={{ width: `${(100 * s.score) / max}%` }} transition={{ duration: 0.9, delay: 0.1 * i }} className={cn("h-full rounded-full", i === 0 ? "bg-red-500" : "bg-white/40")} />
            </div>
          </div>
        ))}
      </div>
      {why && <p className="mt-4 rounded-xl bg-white/[0.05] p-3 text-[13px] leading-snug text-white/85"><span className="text-white/50">Detective: </span>{why}</p>}

      {wo && (
        <div className="mt-5 rounded-xl border border-white/10 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold"><Wrench className="size-4" />Repair order
            <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[11px]", wo.status === "approved" ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-white/70")}>{wo.status}</span>
            {wo.status !== "approved" && <button onClick={() => setEdit(!edit)} className="text-white/50 hover:text-white" aria-label="Edit"><Pencil className="size-3.5" /></button>}
          </div>
          {edit ? (
            <div className="mt-3 space-y-2">
              {(["crew", "parts", "priority"] as const).map((k) => (
                <Input key={k} value={String(draft[k] ?? "")} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} className="h-8 border-white/10 bg-white/5 text-xs text-white" />
              ))}
              <Input value={(draft.valves_to_close ?? []).join(", ")} onChange={(e) => setDraft({ ...draft, valves_to_close: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} className="h-8 border-white/10 bg-white/5 text-xs text-white" />
            </div>
          ) : (
            <dl className="mt-3 grid grid-cols-[80px_1fr] gap-y-1.5 text-[12.5px]">
              <dt className="text-white/45">Close</dt><dd>valves {(draft.valves_to_close ?? wo.valves_to_close).join(", ")}</dd>
              <dt className="text-white/45">Crew</dt><dd>{draft.crew ?? wo.crew}</dd>
              <dt className="text-white/45">Priority</dt><dd>{draft.priority ?? wo.priority}</dd>
            </dl>
          )}
          {wo.status === "approved" ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-emerald-300"><CheckCircle2 className="size-4" />Approved by {wo.approved_by}</div>
          ) : (
            <div className="mt-4 flex gap-2">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Supervisor name" className="h-10 border-white/10 bg-white/5 text-white" />
              <Button onClick={approve} className="h-10 rounded-lg bg-white text-black hover:bg-white/90">Approve</Button>
            </div>
          )}
        </div>
      )}
    </Glass>
  )
}

// ============================================================================ EMERGENCY PLAN
export function PlanControls({ inputs, setInputs, plan }: { inputs: PlanIn; setInputs: (p: PlanIn) => void; plan: Plan | null }) {
  return (
    <Glass className="w-[300px] space-y-5 p-5">
      <div><div className="text-xs uppercase tracking-wider text-white/45">What if…</div><div className="text-lg font-semibold">Pipe is shut off</div></div>
      <Ctl label="Hottest day" value={`${inputs.temp} °F`}>
        <Slider value={[inputs.temp]} min={70} max={102} onValueChange={(v: any) => setInputs({ ...inputs, temp: v[0] ?? v })} />
      </Ctl>
      <Ctl label="Also lose a plant chiller" value={`${fmt(inputs.outage)} tons`}>
        <Slider value={[inputs.outage]} min={0} max={3000} step={250} onValueChange={(v: any) => setInputs({ ...inputs, outage: v[0] ?? v })} />
      </Ctl>
      <Ctl label="Daily budget" value={inputs.budget ? money(inputs.budget) : "no limit"}>
        <Slider value={[inputs.budget]} min={0} max={80000} step={5000} onValueChange={(v: any) => setInputs({ ...inputs, budget: v[0] ?? v })} />
      </Ctl>
      <label className="flex items-center justify-between text-[13px] text-white/75">Use the smart planner
        <Switch checked={inputs.smart} onCheckedChange={(c: boolean) => setInputs({ ...inputs, smart: c })} />
      </label>
      {plan && <p className="text-[11px] text-white/40">Solved in {fmt(plan.solve_ms)} ms · {plan.solver.startsWith("milp") ? "optimizer" : "simple rule"}</p>}
    </Glass>
  )
}
export interface PlanIn { temp: number; outage: number; budget: number; smart: boolean }
function Ctl({ label, value, children }: { label: string; value: string; children: React.ReactNode }) {
  return <div><div className="mb-2 flex justify-between text-[13px]"><span className="text-white/70">{label}</span><span className="font-semibold tabular-nums">{value}</span></div>{children}</div>
}

export function PlanResult({ plan, inputs }: { plan: Plan | null; inputs: PlanIn }) {
  const [names, setNames] = useState({ d: "", f: "" })
  const [alert, setAlert] = useState<Alert | null>(null)
  const [comms, setComms] = useState("")
  const [all, setAll] = useState(false)
  if (!plan) return <Glass className="w-[380px] p-6 text-white/60">Planning…</Glass>
  const [lo, hi] = plan.uw_actual_usd_per_day
  const max = Math.max(hi * 1.1, plan.cost_usd_per_day * 1.1)
  const closed = plan.buildings.filter((b) => b.status === "closed")

  async function approve() {
    try {
      const saved = await api.plan({ ...body(inputs), save: true })
      const r = await api.approvePlan(saved.id!, { "FP&M director": names.d, "VC for Finance": names.f })
      if (r.missing.length) return toast.error("Still needs: " + r.missing.join(", "))
      toast.success("Plan approved. Messenger is drafting the campus email.")
      setAlert(r.alert ?? null); setComms("")
    } catch (e: any) { toast.error(e.message) }
  }
  return (
    <>
      <Glass className="w-[380px] p-5">
        <div className="grid grid-cols-2 gap-4">
          <Stat label="Rental cost / day"><CountUp value={plan.cost_usd_per_day} prefix="$" /></Stat>
          <Stat label="Buildings open"><CountUp value={plan.kept_open} /><span className="text-white/40"> / {plan.kept_open + plan.closed}</span></Stat>
          <Stat label="Rented chillers"><CountUp value={plan.rented_units} /></Stat>
          <Stat label="Diesel / day"><CountUp value={plan.diesel_gal_per_day} suffix=" gal" /></Stat>
        </div>
        <div className="mt-5 text-[12px] text-white/55">vs. UW's estimated cost in 2026</div>
        <div className="relative mt-2 h-2.5 rounded-full bg-white/10">
          <div className="absolute h-full rounded-full bg-white/25" style={{ left: `${(100 * lo) / max}%`, width: `${(100 * (hi - lo)) / max}%` }} />
          <motion.div className="absolute -top-1 h-4.5 w-1 rounded bg-white" animate={{ left: `${(100 * plan.cost_usd_per_day) / max}%` }} transition={{ type: "spring", stiffness: 120, damping: 18 }} />
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-white/40"><span>this plan</span><span>{money(lo)}–{money(hi)}</span></div>
        {closed.length > 0 && <p className="mt-4 text-[13px] text-white/75"><span className="text-red-400">Close:</span> {closed.map((b) => b.name).join(", ")}</p>}
        <button onClick={() => setAll(true)} className="mt-2 text-[12px] text-white/50 underline-offset-2 hover:underline">See every building</button>
        <div className="mt-5 space-y-2 border-t border-white/10 pt-4">
          <div className="text-[12px] text-white/55">Spending money needs two people.</div>
          <Input value={names.d} onChange={(e) => setNames({ ...names, d: e.target.value })} placeholder="FP&M director" className="h-9 border-white/10 bg-white/5 text-white" />
          <Input value={names.f} onChange={(e) => setNames({ ...names, f: e.target.value })} placeholder="VC for Finance" className="h-9 border-white/10 bg-white/5 text-white" />
          <Button onClick={approve} className="h-11 w-full rounded-xl bg-white text-black hover:bg-white/90">Approve plan</Button>
        </div>
      </Glass>

      <Dialog open={all} onOpenChange={setAll}>
        <DialogContent className="max-h-[80vh] overflow-y-auto border-white/10 bg-[#0b0f15] text-white sm:max-w-2xl">
          <DialogHeader><DialogTitle>Every east-campus building</DialogTitle><DialogDescription className="text-white/50">At the hottest hour of the next 3 days.</DialogDescription></DialogHeader>
          <div className="space-y-1.5">
            {[...plan.buildings].sort((a, b) => a.served_pct - b.served_pct).map((b) => (
              <div key={b.building_id} className="grid grid-cols-[1fr_120px_60px] items-center gap-3 text-[13px]">
                <div className="truncate">{b.name} <span className="text-white/40">· {b.use}</span></div>
                <div className="h-1.5 rounded-full bg-white/10"><div className={cn("h-full rounded-full", b.status === "closed" ? "bg-red-500" : b.served_pct < 100 ? "bg-amber-400" : "bg-zinc-300")} style={{ width: `${b.served_pct}%` }} /></div>
                <div className="text-right tabular-nums text-white/70">{b.status === "closed" ? "closed" : `${b.served_pct}%`}</div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!alert} onOpenChange={(o) => !o && setAlert(null)}>
        <DialogContent className="border-white/10 bg-[#0b0f15] text-white sm:max-w-xl">
          <DialogHeader><DialogTitle>Campus email (draft)</DialogTitle><DialogDescription className="text-white/50">Written by the Messenger agent. Nothing is sent until Communications approves.</DialogDescription></DialogHeader>
          {alert && <>
            <Textarea defaultValue={alert.body} id="alert-body" rows={10} className="border-white/10 bg-white/5 text-[13px] text-white" />
            {alert.status === "draft" ? (
              <div className="flex gap-2">
                <Input value={comms} onChange={(e) => setComms(e.target.value)} placeholder="Communications approver" className="border-white/10 bg-white/5 text-white" />
                <Button onClick={async () => {
                  try { const a = await api.approveAlert(alert.id, comms, (document.getElementById("alert-body") as HTMLTextAreaElement).value); setAlert(a); toast.success("Email approved (demo: not sent).") }
                  catch (e: any) { toast.error(e.message) }
                }} className="bg-white text-black hover:bg-white/90">Approve</Button>
              </div>
            ) : <div className="flex items-center gap-2 text-sm text-emerald-300"><CheckCircle2 className="size-4" />Approved by {alert.approved_by}</div>}
          </>}
        </DialogContent>
      </Dialog>
    </>
  )
}
export const body = (i: PlanIn) => ({ forecast_max_f: i.temp, extra_outage_tons: i.outage, budget_usd_per_day: i.budget || null, solver: i.smart ? "auto" : "greedy" })

// ============================================================================ FIX LIST
export function FixPanel() {
  const [budget, setBudget] = useState(15)
  const [data, setData] = useState<{ ranking: RepairRow[]; request: string; selected_cost_usd: number; selected_benefit_usd: number; n_selected: number } | null>(null)
  const [show, setShow] = useState(false)
  useEffect(() => { const h = setTimeout(() => api.repairs(budget * 1e6).then(setData), 150); return () => clearTimeout(h) }, [budget])
  const rows = data?.ranking.slice(0, 9) ?? []
  const top = Math.max(...rows.map((r) => r.expected_loss_usd), 1)
  return (
    <Glass className="w-[400px] p-5">
      <div className="text-xs uppercase tracking-wider text-white/45">Fix before it breaks</div>
      <div className="mt-1 flex items-baseline justify-between"><div className="text-lg font-semibold">Budget</div><div className="text-lg font-semibold tabular-nums">${budget}M</div></div>
      <Slider className="mt-2" value={[budget]} min={2} max={40} onValueChange={(v: any) => setBudget(v[0] ?? v)} />
      {data && <p className="mt-3 text-[13px] text-white/70">Replace <b className="text-white">{data.n_selected} pipes</b> for {money(data.selected_cost_usd)}. Avoids about <b className="text-white">{money(data.selected_benefit_usd)}</b> of losses over 10 years.</p>}
      <div className="mt-4 space-y-2">
        {rows.map((r) => (
          <div key={r.pipe_id} className="grid grid-cols-[80px_1fr_74px] items-center gap-2 text-[12.5px]">
            <div className="flex items-center gap-1.5"><span className={cn("size-2 rounded-full", riskDot[r.risk_label])} />{r.pipe_id}</div>
            <div className="h-1.5 rounded-full bg-white/10"><motion.div className={cn("h-full rounded-full", r.selected ? "bg-white" : "bg-white/30")} animate={{ width: `${(100 * r.expected_loss_usd) / top}%` }} /></div>
            <div className="text-right tabular-nums text-white/60">{money(Math.round(r.expected_loss_usd / 1000))}K</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-white/40">Bar = expected loss if we wait. White = in the plan. Map shows pipe health.</p>
      <Button onClick={() => setShow(true)} className="mt-4 h-10 w-full rounded-xl bg-white text-black hover:bg-white/90">Draft the funding request</Button>
      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="border-white/10 bg-[#0b0f15] text-white sm:max-w-xl">
          <DialogHeader><DialogTitle>Request to the Regents (draft)</DialogTitle></DialogHeader>
          <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-white/85">{data?.request}</pre>
        </DialogContent>
      </Dialog>
    </Glass>
  )
}

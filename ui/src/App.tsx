import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { Droplets, Globe2, Map as MapIcon } from "lucide-react"
import { toast } from "sonner"
import { Toaster } from "@/components/ui/sonner"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api, type FeedItem, type Geo, type Meta, type Plan, type State } from "@/lib/api"
import { CampusMap, type MapHandle } from "@/components/CampusMap"
import { Intro } from "@/components/Intro"
import { Timeline } from "@/components/Timeline"
import { Agents } from "@/components/Agents"
import { FixPanel, IncidentPanel, PlanControls, PlanResult, StatusPanel, body, type PlanIn } from "@/components/Panels"
import { InfoSheet } from "@/components/InfoSheet"

type Tab = "live" | "incident" | "plan" | "fix"

function hourList(meta: Meta) {
  const out: string[] = []
  const p = (n: number) => String(n).padStart(2, "0")
  const start = new Date(meta.replay_start.replace(" ", "T")).getTime() + 24 * 3600e3
  const end = new Date(meta.replay_end.replace(" ", "T")).getTime()
  for (let t = start; t <= end; t += 3600e3) {
    const d = new Date(t)
    out.push(`${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:00`)
  }
  return out
}

export default function App() {
  const q = new URLSearchParams(location.search)
  const [intro, setIntro] = useState(!q.has("skip"))
  const [meta, setMeta] = useState<Meta | null>(null)
  const [geo, setGeo] = useState<Geo | null>(null)
  const [hours, setHours] = useState<string[]>([])
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(6)
  const [state, setState] = useState<State | null>(null)
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [tab, setTab] = useState<Tab>((q.get("tab") as Tab) || "live")
  const [basemap, setBasemap] = useState<"satellite" | "dark">("satellite")
  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [planIn, setPlanIn] = useState<PlanIn>({ temp: 95, outage: 0, budget: 0, smart: true })
  const [plan, setPlan] = useState<Plan | null>(null)
  const [question, setQuestion] = useState("")
  const mapRef = useRef<MapHandle>(null)
  const lastKind = useRef<string>("normal")
  const t = hours[idx] ?? ""

  // boot
  useEffect(() => {
    Promise.all([api.meta(), api.geo()]).then(([m, g]) => {
      setMeta(m); setGeo(g)
      const hs = hourList(m); setHours(hs)
      const start = hs.indexOf(q.get("t") || "2026-06-05 12:00")
      setIdx(start >= 0 ? start : 0)
    }).catch((e) => toast.error("Can't reach the server: " + e.message))
  }, [])

  // replay clock
  useEffect(() => {
    if (!playing) return
    const h = setInterval(() => setIdx((i) => (i + speed >= hours.length - 1 ? (setPlaying(false), hours.length - 1) : i + speed)), 260)
    return () => clearInterval(h)
  }, [playing, speed, hours.length])

  // fetch state + agent feed for the current hour (latest wins)
  const seq = useRef(0)
  useEffect(() => {
    if (!t) return
    const my = ++seq.current
    Promise.all([api.state(t), api.agents(t)]).then(([s, a]) => {
      if (my !== seq.current) return
      setState(s); setFeed(a.feed)
      if (s.open_incidents[0] && !incidentId) setIncidentId(s.open_incidents[0].id)
    })
  }, [t])

  // cinematic reactions to big moments
  useEffect(() => {
    if (!state || !geo) return
    const k = state.leak.kind
    if (k !== lastKind.current) {
      const m01 = geo.pipes.features.find((f) => f.properties.pipe_id === "CW-M01")!.geometry.coordinates
      const mid = [(m01[0][0] + m01[1][0]) / 2, (m01[0][1] + m01[1][1]) / 2]
      if (k === "leak" && lastKind.current === "normal") { toast.warning("Watcher: water is going missing near Charter St."); mapRef.current?.flyTo(mid[0], mid[1], 16.4) }
      if (k === "burst") { toast.error("Pipe burst at Charter St."); mapRef.current?.flyTo(mid[0], mid[1], 17) }
      if (k === "isolated" && lastKind.current === "burst") { toast("Valves closed. Planner is on it."); mapRef.current?.home() }
      if (k === "normal" && lastKind.current !== "normal") mapRef.current?.home()
      lastKind.current = k
    }
  }, [state?.leak.kind, geo])

  // plan solves live as the sliders move
  useEffect(() => {
    if (tab !== "plan") return
    const h = setTimeout(() => api.plan(body(planIn)).then(setPlan).catch((e) => toast.error(e.message)), 180)
    return () => clearTimeout(h)
  }, [tab, planIn])

  const openCase = useCallback(async () => {
    try {
      if (!incidentId) { const r = await api.openIncident(t); setIncidentId(r.incident.id); toast.success("Case opened. Repair order drafted.") }
      setTab("incident"); setPlaying(false)
    } catch (e: any) { toast.error(e.message) }
  }, [incidentId, t])

  const onPick = useCallback((w: { kind: string; id: string; name: string }) => {
    setQuestion(w.kind === "pipe" ? `How old is ${w.id} and what has failed near it?` : `Tell me about ${w.name}?`)
  }, [])

  const tabs = useMemo(() => [["live", "Live"], ["incident", "Case"], ["plan", "Emergency plan"], ["fix", "Fix first"]] as const, [])

  return (
    <div className="dark fixed inset-0 overflow-hidden bg-[#07090c] font-sans text-white">
      <CampusMap ref={mapRef} geo={geo} state={state} plan={tab === "plan" ? plan : null} mode={tab === "plan" ? "plan" : tab === "fix" ? "fix" : "live"} basemap={basemap} startOnCampus={!intro} onPick={onPick} />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-black/70 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/70 to-transparent" />

      {/* top bar */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center gap-4 px-5 py-4">
        <div className="pointer-events-auto flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-xl bg-white text-black"><Droplets className="size-5" /></div>
          <div><div className="font-semibold leading-none">BadgerTwin</div><div className="mt-0.5 text-[11px] text-white/50">UW–Madison chilled water</div></div>
        </div>
        <Tabs value={tab} onValueChange={(v: any) => setTab(v)} className="pointer-events-auto mx-auto">
          <TabsList className="h-10 rounded-full border border-white/10 bg-black/45 p-1 backdrop-blur-xl">
            {tabs.map(([v, l]) => (
              <TabsTrigger key={v} value={v} className="rounded-full px-4 text-[13px] text-white/65 data-[active]:bg-white data-[active]:text-black">{l}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="pointer-events-auto flex items-center gap-2">
          <ToggleGroup value={[basemap]} onValueChange={(v: any) => v?.[0] && setBasemap(v[0])} className="rounded-full border border-white/10 bg-black/45 p-0.5 backdrop-blur-xl">
            <ToggleGroupItem value="satellite" aria-label="Satellite" className="size-8 rounded-full data-[pressed]:bg-white/20"><Globe2 className="size-4" /></ToggleGroupItem>
            <ToggleGroupItem value="dark" aria-label="Map" className="size-8 rounded-full data-[pressed]:bg-white/20"><MapIcon className="size-4" /></ToggleGroupItem>
          </ToggleGroup>
          <InfoSheet onReset={() => { setIncidentId(null) }} />
        </div>
      </header>

      {/* panels */}
      <div className="pointer-events-none absolute left-5 top-20 z-10 flex flex-col gap-3">
        <AnimatePresence mode="wait">
          {tab === "live" && state && <motion.div key="s"><StatusPanel state={state} onOpen={openCase} hasCase={!!incidentId} /></motion.div>}
          {tab === "incident" && <motion.div key="i"><IncidentPanel incidentId={incidentId} /></motion.div>}
          {tab === "plan" && <motion.div key="p"><PlanControls inputs={planIn} setInputs={setPlanIn} plan={plan} /></motion.div>}
          {tab === "fix" && <motion.div key="f"><FixPanel /></motion.div>}
        </AnimatePresence>
      </div>
      <div className="pointer-events-none absolute right-5 top-20 z-10">
        <AnimatePresence mode="wait">
          {tab === "plan" ? <motion.div key="pr"><PlanResult plan={plan} inputs={planIn} /></motion.div>
            : <motion.div key="ag"><Agents feed={feed} t={t} question={question} setQuestion={setQuestion} /></motion.div>}
        </AnimatePresence>
      </div>
      {(tab === "live" || tab === "incident") && meta && (
        <div className="pointer-events-none absolute inset-x-0 bottom-5 z-10 flex justify-center">
          <Timeline hours={hours} idx={idx} setIdx={(i) => i >= 0 && setIdx(i)} playing={playing} setPlaying={setPlaying} speed={speed} setSpeed={setSpeed} outdoor={state?.outdoor_f ?? null} />
        </div>
      )}
      <div className="pointer-events-none absolute bottom-1.5 left-5 z-10 text-[10.5px] text-white/40">Simulated data built from public facts · pipe routes are approximate</div>

      <AnimatePresence>{intro && <Intro onStart={() => { setIntro(false); mapRef.current?.intro(); setTimeout(() => setPlaying(true), 6200) }} />}</AnimatePresence>
      <Toaster position="top-center" theme="dark" richColors />
    </div>
  )
}

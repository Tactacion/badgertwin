import { useEffect, useState } from "react"
import { Area, AreaChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts"
import { BookOpen, X } from "lucide-react"
import { ChartContainer } from "@/components/ui/chart"
import { api, fmt, type History, type Point } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Glass, riskDot } from "./bits"

/** Click a building or pipe → its story in one clean card (inspired by Electricity Maps). */
export function DetailPanel({ id, t, onClose, onAsk }: { id: string; t: string; onClose: () => void; onAsk: (q: string) => void }) {
  const [h, setH] = useState<History | null>(null)
  useEffect(() => { setH(null); api.history(id, t).then(setH).catch(() => setH(null)) }, [id, t.slice(0, 13)])
  return (
    <Glass className="w-[360px] p-5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] uppercase tracking-wider text-white/45">{h?.kind === "pipe" ? `${h.role} pipe` : h?.use ?? "…"}</div>
          <div className="truncate text-xl font-semibold">{h?.kind === "pipe" ? h.id : h?.name ?? id}</div>
        </div>
        <button onClick={onClose} className="grid size-8 place-items-center rounded-full bg-white/5 text-white/60 hover:text-white" aria-label="Close"><X className="size-4" /></button>
      </div>
      {!h ? <div className="mt-6 h-40 animate-pulse rounded-xl bg-white/5" /> : h.kind === "building" ? (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {h.patient_care && <Tag>patient care</Tag>}
            {h.animal_research && <Tag>animal research</Tag>}
            {h.affected && <Tag tone="amber">hit in 2026 · {h.status_2026}</Tag>}
            <Tag>{fmt(h.tons)} tons at peak</Tag>
          </div>
          <Chart title="Inside temperature" unit="°F" data={h.indoor ?? []} line={h.limit_f} lineLabel={`limit ${h.limit_f} °F`} color="#fbbf24" />
          <Chart title="Chilled water in" unit="gal/min" data={h.flow} color="#7dd3fc" />
        </>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Mini k={`${h.diameter}"`} l="size" /><Mini k={String(h.install_year)} l="built" /><Mini k={`${h.depth_ft} ft`} l="deep" />
          </div>
          <div className="mt-3 flex items-center gap-2 text-[13px]">
            <span className={cn("size-2 rounded-full", riskDot[h.health ?? "Normal"])} />
            <b>{h.health}</b><span className="text-white/55">· {Math.round((h.risk ?? 0) * 100)}% chance of failing in 10 years</span>
          </div>
          <p className="mt-1 text-[12px] text-white/45">{h.material} · {h.from_node} → {h.to_node}</p>
          <Chart title="Water flowing" unit="gal/min" data={h.flow} color="#7dd3fc" />
          {(h.pressure?.length ?? 0) > 0 && <Chart title={`Pressure at ${h.from_node}`} unit="psi" data={h.pressure!} color="#c4b5fd" />}
        </>
      )}
      {h && (
        <button onClick={() => onAsk(h.kind === "pipe" ? `How old is ${h.id} and what has failed near it?` : `Tell me about ${h.name}?`)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 py-2 text-[13px] text-white/80 hover:bg-white/10">
          <BookOpen className="size-4" />Ask the Librarian
        </button>
      )}
      <p className="mt-2 text-[10.5px] text-white/35">Last 7 days · simulated sensors</p>
    </Glass>
  )
}

function Tag({ children, tone }: { children: React.ReactNode; tone?: "amber" }) {
  return <span className={cn("rounded-full border px-2 py-0.5 text-[11px]", tone === "amber" ? "border-amber-400/40 text-amber-300" : "border-white/10 text-white/70")}>{children}</span>
}
function Mini({ k, l }: { k: string; l: string }) {
  return <div className="rounded-xl bg-white/5 py-2"><div className="text-[15px] font-semibold">{k}</div><div className="text-[10.5px] text-white/45">{l}</div></div>
}
function Chart({ title, unit, data, color, line, lineLabel }: { title: string; unit: string; data: Point[]; color: string; line?: number; lineLabel?: string }) {
  const last = data.at(-1)?.v
  const id = "g" + title.replace(/\W/g, "")
  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between text-[12px]"><span className="text-white/60">{title}</span><span className="font-semibold tabular-nums">{fmt(last, unit === "°F" ? 1 : 0)} <span className="font-normal text-white/45">{unit}</span></span></div>
      <ChartContainer config={{ v: { label: title, color } }} className="mt-1 h-20 w-full">
        <AreaChart data={data} margin={{ top: 6, right: 4, left: 4, bottom: 0 }}>
          <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.45} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs>
          <XAxis dataKey="t" hide /><YAxis hide domain={["auto", "auto"]} />
          <Tooltip cursor={{ stroke: "rgba(255,255,255,0.25)" }} contentStyle={{ background: "rgba(0,0,0,0.8)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: "rgba(255,255,255,0.6)" }} formatter={(v: any) => [`${fmt(Number(v), 1)} ${unit}`, ""]} />
          {line != null && <ReferenceLine y={line} stroke="rgba(255,90,90,0.7)" strokeDasharray="3 3" label={{ value: lineLabel, fill: "rgba(255,140,140,0.9)", fontSize: 10, position: "insideTopRight" }} />}
          <Area dataKey="v" type="monotone" stroke={color} strokeWidth={1.8} fill={`url(#${id})`} animationDuration={700} />
        </AreaChart>
      </ChartContainer>
    </div>
  )
}

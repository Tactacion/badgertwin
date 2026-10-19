import { Pause, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Glass } from "./bits"

export const MOMENTS = [
  { t: "2026-06-05 12:00", label: "Normal" },
  { t: "2026-06-08 14:00", label: "Leak spotted" },
  { t: "2026-06-14 12:00", label: "Leak grows" },
  { t: "2026-06-17 15:00", label: "Burst" },
  { t: "2026-06-19 15:00", label: "Cooling cut" },
  { t: "2026-08-10 12:00", label: "Fixed" },
]

interface Props {
  hours: string[]; idx: number; setIdx: (i: number) => void
  playing: boolean; setPlaying: (p: boolean) => void; speed: number; setSpeed: (s: number) => void; outdoor: number | null
}

export function Timeline({ hours, idx, setIdx, playing, setPlaying, speed, setSpeed, outdoor }: Props) {
  const t = hours[idx] ?? ""
  const d = t ? new Date(t.replace(" ", "T")) : null
  const pos = (s: string) => (100 * Math.max(0, hours.indexOf(s))) / Math.max(1, hours.length - 1)
  return (
    <Glass className="w-[min(920px,calc(100vw-32px))] px-5 pb-4 pt-3" delay={0.2}>
      <div className="flex items-center gap-4">
        <Button size="icon" onClick={() => setPlaying(!playing)} className="size-10 shrink-0 rounded-full bg-white text-black hover:bg-white/90" aria-label={playing ? "Pause" : "Play"}>
          {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}
        </Button>
        <div className="min-w-[150px]">
          <div className="text-lg font-semibold tabular-nums">{d?.toLocaleDateString("en-US", { month: "short", day: "numeric" })} · {d?.toLocaleTimeString("en-US", { hour: "numeric" })}</div>
          <div className="text-xs text-white/50">{outdoor != null ? `${Math.round(outdoor)} °F outside` : " "}</div>
        </div>
        <div className="relative flex-1">
          <div className="mb-2.5 flex flex-wrap gap-1">
            {MOMENTS.map((m) => {
              const here = Math.abs(hours.indexOf(m.t) - idx) < 3
              return (
                <button key={m.t} onClick={() => setIdx(hours.indexOf(m.t))}
                  className={"rounded-full border px-2 py-0.5 text-[11px] transition " + (here ? "border-white/60 bg-white text-black" : "border-white/10 bg-white/5 text-white/60 hover:text-white")}>
                  {m.label}
                </button>
              )
            })}
          </div>
          {MOMENTS.map((m) => (
            <span key={m.t} style={{ left: `${pos(m.t)}%` }} className="pointer-events-none absolute bottom-[-6px] h-1.5 w-px bg-white/40" />
          ))}
          <Slider value={[idx]} min={0} max={Math.max(0, hours.length - 1)} onValueChange={(v: any) => setIdx(Array.isArray(v) ? v[0] : v)} aria-label="Replay time" />
        </div>
        <ToggleGroup value={[String(speed)]} onValueChange={(v: any) => v?.[0] && setSpeed(Number(v[0]))} className="shrink-0">
          {[1, 6, 24].map((s) => (
            <ToggleGroupItem key={s} value={String(s)} className="h-8 px-2 text-xs data-[pressed]:bg-white/15">{s === 1 ? "1h" : s === 6 ? "6h" : "1d"}/s</ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
    </Glass>
  )
}

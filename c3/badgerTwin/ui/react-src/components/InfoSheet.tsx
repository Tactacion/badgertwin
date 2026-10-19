import { useEffect, useState } from "react"
import { Info } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { api } from "@/lib/api"

export function InfoSheet({ onReset }: { onReset: () => void }) {
  const [open, setOpen] = useState(false)
  const [src, setSrc] = useState<Awaited<ReturnType<typeof api.sources>>["sources"]>([])
  const [audit, setAudit] = useState<Awaited<ReturnType<typeof api.audit>>["audit"]>([])
  useEffect(() => { if (open) { api.sources().then((s) => setSrc(s.sources)); api.audit().then((a) => setAudit(a.audit)) } }, [open])
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<button className="grid size-9 place-items-center rounded-full border border-white/10 bg-black/40 text-white/80 backdrop-blur hover:text-white" aria-label="Sources and log" />}>
        <Info className="size-4" />
      </SheetTrigger>
      <SheetContent className="w-[420px] overflow-y-auto border-white/10 bg-[#0b0f15] text-white sm:max-w-md">
        <SheetHeader><SheetTitle className="text-white">What's real</SheetTitle></SheetHeader>
        <div className="space-y-6 px-4 pb-8 text-[13px]">
          <ul className="space-y-1.5 text-white/75">
            <li><b className="text-white">Real:</b> the 2026 and 1980 failures, the 34 buildings, costs, weather, campus map.</li>
            <li><b className="text-white">Estimated:</b> building cooling needs, rental prices.</li>
            <li><b className="text-white">Simulated:</b> the pipe network and every sensor reading.</li>
          </ul>
          <div>
            <div className="mb-2 font-semibold">Sources</div>
            <ul className="space-y-2">{src.map((s, i) => (
              <li key={i}><a href={/^https?:/.test(s.url) ? s.url : "#"} target="_blank" rel="noopener" className="underline-offset-2 hover:underline">{s.title || s.url}</a><div className="text-white/40">{s.publisher} · {s.date}</div></li>
            ))}</ul>
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between font-semibold">Who approved what
              <Button size="sm" variant="ghost" className="h-7 text-white/60" onClick={async () => { await api.reset(); setAudit([]); onReset(); toast("Demo reset") }}>Reset demo</Button>
            </div>
            {audit.length === 0 ? <div className="text-white/40">Nothing yet.</div> : (
              <ul className="space-y-1">{audit.map((a, i) => <li key={i} className="flex gap-2"><span className="text-white/40 tabular-nums">{a.at.slice(11, 19)}</span><span>{a.actor}</span><span className="text-white/55">{a.action.replaceAll("_", " ")}</span></li>)}</ul>
            )}
          </div>
          <p className="text-[11px] text-white/35">Imagery: Esri, Vantor, Earthstar Geographics. Map data: OpenFreeMap, OpenMapTiles, OpenStreetMap. Photo: Richard Hurd, CC BY 2.0.</p>
        </div>
      </SheetContent>
    </Sheet>
  )
}

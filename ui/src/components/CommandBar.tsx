import { useEffect, useState } from "react"
import { Building2, Clock, LayoutGrid, Waypoints } from "lucide-react"
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from "@/components/ui/command"
import type { Geo } from "@/lib/api"
import { MOMENTS } from "./Timeline"

/** ⌘K: jump to any moment, screen, building or pipe (inspired by Linear). */
export function CommandBar({ geo, onTab, onMoment, onPick }: {
  geo: Geo | null; onTab: (t: "live" | "incident" | "plan" | "fix") => void; onMoment: (t: string) => void; onPick: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o) } }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [])
  const go = (f: () => void) => { f(); setOpen(false) }
  const trunks = geo?.pipes.features.filter((f) => f.properties.role !== "lateral") ?? []
  return (
    <>
      <button onClick={() => setOpen(true)} className="pointer-events-auto hidden h-9 items-center gap-2 rounded-full border border-white/10 bg-black/45 px-3 text-[12px] text-white/55 backdrop-blur-xl hover:text-white md:flex">
        Search <kbd className="rounded bg-white/10 px-1.5 font-mono text-[10px]">⌘K</kbd>
      </button>
      <CommandDialog open={open} onOpenChange={setOpen} className="border-white/10 bg-[#0b0f15] text-white">
        <Command className="bg-transparent text-white">
          <CommandInput placeholder="Jump to a building, pipe, moment…" />
          <CommandList className="max-h-[380px]">
            <CommandEmpty>Nothing found.</CommandEmpty>
            <CommandGroup heading="Screens">
              {([["live", "Live"], ["incident", "Case"], ["plan", "Emergency plan"], ["fix", "Fix first"]] as const).map(([v, l]) => (
                <CommandItem key={v} onSelect={() => go(() => onTab(v))}><LayoutGrid />{l}</CommandItem>
              ))}
            </CommandGroup>
            <CommandGroup heading="Moments">
              {MOMENTS.map((m) => <CommandItem key={m.t} onSelect={() => go(() => onMoment(m.t))}><Clock />{m.label}<CommandShortcut>{m.t.slice(5, 10)}</CommandShortcut></CommandItem>)}
            </CommandGroup>
            <CommandGroup heading="Buildings">
              {geo?.buildings.features.map((f) => (
                <CommandItem key={f.properties.building_id} value={f.properties.name} onSelect={() => go(() => onPick(f.properties.building_id))}>
                  <Building2 />{f.properties.name}<CommandShortcut>{f.properties.use}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandGroup heading="Main pipes">
              {trunks.map((f) => (
                <CommandItem key={f.properties.pipe_id} value={f.properties.pipe_id} onSelect={() => go(() => onPick(f.properties.pipe_id))}>
                  <Waypoints />{f.properties.pipe_id}<CommandShortcut>{f.properties.diameter}" · {f.properties.install_year}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  )
}

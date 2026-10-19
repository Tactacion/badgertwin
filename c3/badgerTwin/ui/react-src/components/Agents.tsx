import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { BookOpen, ClipboardList, Eye, Megaphone, Search, Send, Snowflake, UserCheck } from "lucide-react"
import { Input } from "@/components/ui/input"
import { api, niceTime, type FeedItem } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Glass } from "./bits"

const ICON: Record<string, any> = { watcher: Eye, detective: Search, dispatcher: ClipboardList, planner: Snowflake, messenger: Megaphone, librarian: BookOpen, person: UserCheck }
const ROLE: Record<string, string> = { watcher: "watches sensors", detective: "finds the cause", dispatcher: "writes repair orders", planner: "plans cooling", messenger: "drafts campus alerts", librarian: "answers questions" }
const LEVEL = { info: "border-white/10", watch: "border-amber-400/40", act: "border-red-500/50" }

export function Agents({ feed, t, question, setQuestion }: { feed: FeedItem[]; t: string; question: string; setQuestion: (q: string) => void }) {
  const [answer, setAnswer] = useState<{ q: string; a: string; cites: { title: string; url: string }[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const list = useRef<HTMLDivElement>(null)
  const active = new Set(feed.slice(-3).map((f) => f.agent))
  const items = [...feed].reverse().slice(0, 12)

  useEffect(() => { list.current?.scrollTo({ top: 0, behavior: "smooth" }) }, [feed.length])

  async function ask(q = question) {
    if (!q.trim()) return
    setBusy(true)
    try { const r = await api.ask(q, t); setAnswer({ q, a: r.answer, cites: r.citations }) } finally { setBusy(false) }
  }
  useEffect(() => { if (question.endsWith("?")) ask(question) }, [question]) // map clicks fill a question

  return (
    <Glass className="flex max-h-[calc(100vh-220px)] w-[360px] flex-col overflow-hidden" delay={0.35}>
      <div className="border-b border-white/10 px-4 pb-3 pt-4">
        <div className="text-sm font-semibold">AI agents</div>
        <div className="mt-3 flex gap-2">
          {["watcher", "detective", "dispatcher", "planner", "messenger", "librarian"].map((a) => {
            const I = ICON[a]
            return (
              <div key={a} title={`${a[0].toUpperCase() + a.slice(1)}: ${ROLE[a]}`}
                className={cn("relative grid size-9 place-items-center rounded-xl border transition", active.has(a) ? "border-white/40 bg-white/15" : "border-white/10 bg-white/5")}>
                <I className="size-4 text-white/85" />
                {active.has(a) && <span className="absolute -right-0.5 -top-0.5 size-2 animate-pulse rounded-full bg-emerald-400" />}
              </div>
            )
          })}
        </div>
      </div>
      <div ref={list} className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        <AnimatePresence initial={false}>
          {items.map((f) => {
            const I = ICON[f.agent] ?? UserCheck
            return (
              <motion.div key={f.at + f.agent + f.text} layout
                initial={{ opacity: 0, x: 24, scale: 0.97 }} animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                className={cn("rounded-xl border bg-white/[0.03] p-3", LEVEL[f.level] ?? LEVEL.info)}>
                <div className="flex items-center gap-2 text-xs text-white/55">
                  <I className="size-3.5" /><span className="font-medium text-white/80">{f.name}</span>
                  <span className="ml-auto tabular-nums">{f.live ? "just now" : niceTime(f.at)}</span>
                </div>
                <div className="mt-1 text-[13px] leading-snug text-white/90">{f.text}</div>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
      <div className="border-t border-white/10 p-3">
        <AnimatePresence>
          {answer && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
              className="mb-2 max-h-48 overflow-y-auto rounded-xl bg-white/[0.06] p-3 text-[12.5px] leading-snug">
              <div className="mb-1 flex items-center gap-1.5 text-xs text-white/55"><BookOpen className="size-3.5" />Librarian</div>
              <div className="whitespace-pre-wrap text-white/90">{answer.a}</div>
              {answer.cites.length > 0 && (
                <div className="mt-2 text-[11px] text-white/45">
                  {answer.cites.map((c, i) => c.url ? <a key={i} href={c.url} target="_blank" rel="noopener" className="mr-2 underline">{c.title.slice(0, 40)}</a> : <span key={i} className="mr-2">{c.title}</span>)}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
        <form onSubmit={(e) => { e.preventDefault(); ask() }} className="flex gap-2">
          <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about any pipe or building"
            className="h-9 border-white/10 bg-white/5 text-sm text-white placeholder:text-white/35" />
          <button disabled={busy} className="grid size-9 shrink-0 place-items-center rounded-lg bg-white text-black disabled:opacity-50" aria-label="Ask"><Send className="size-4" /></button>
        </form>
      </div>
    </Glass>
  )
}

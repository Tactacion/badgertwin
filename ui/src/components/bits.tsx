import { useEffect, useRef, useState, type ReactNode } from "react"
import { motion } from "motion/react"
import { cn } from "@/lib/utils"
import { fmt } from "@/lib/api"

/** Frosted floating panel over the map. */
export function Glass({ className, children, delay = 0 }: { className?: string; children: ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 12, filter: "blur(6px)" }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn("pointer-events-auto rounded-2xl border border-white/10 bg-[#0b0f15]/70 text-white shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl", className)}
    >
      {children}
    </motion.div>
  )
}

/** Number that counts to its new value. */
export function CountUp({ value, digits = 0, prefix = "", suffix = "", className }: { value: number; digits?: number; prefix?: string; suffix?: string; className?: string }) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    const start = performance.now(), a = from.current, b = value, dur = 900
    let raf = 0
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - k, 3)
      setShown(a + (b - a) * e)
      if (k < 1) raf = requestAnimationFrame(tick)
      else from.current = b
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <span className={cn("tabular-nums", className)}>{prefix}{fmt(shown, digits)}{suffix}</span>
}

export const riskText = { Normal: "text-zinc-300", Watch: "text-amber-400", Act: "text-red-400", Closed: "text-red-400" } as const
export const riskDot = { Normal: "bg-zinc-400", Watch: "bg-amber-400", Act: "bg-red-500", Closed: "bg-red-500" } as const

export function Pulse({ color = "bg-red-500" }: { color?: string }) {
  return (
    <span className="relative flex size-2.5">
      <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", color)} />
      <span className={cn("relative inline-flex size-2.5 rounded-full", color)} />
    </span>
  )
}

export function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-white/45">{label}</div>
      <div className="text-xl font-semibold">{children}</div>
    </div>
  )
}

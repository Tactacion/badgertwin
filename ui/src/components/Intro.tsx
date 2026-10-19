import { motion } from "motion/react"
import { Button } from "@/components/ui/button"
import { CountUp } from "./bits"

// Photo: "Bascom Hall on the UW Madison campus" by Richard Hurd, CC BY 2.0, via Wikimedia Commons.
const PHOTO = "https://upload.wikimedia.org/wikipedia/commons/thumb/5/51/Bascom_Hall_on_the_UW_Madison_campus_in_Madison%2C_WI_%286351014921%29.jpg/1280px-Bascom_Hall_on_the_UW_Madison_campus_in_Madison%2C_WI_%286351014921%29.jpg"

const line = (d: number) => ({ initial: { opacity: 0, y: 18, filter: "blur(8px)" }, animate: { opacity: 1, y: 0, filter: "blur(0px)" }, transition: { delay: d, duration: 0.9, ease: [0.22, 1, 0.36, 1] as const } })

export function Intro({ onStart }: { onStart: () => void }) {
  return (
    <motion.div className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden bg-black text-white"
      exit={{ opacity: 0, scale: 1.04, transition: { duration: 0.9 } }}>
      <motion.img src={PHOTO} alt="" className="absolute inset-0 h-full w-full object-cover"
        initial={{ scale: 1.15, opacity: 0 }} animate={{ scale: 1, opacity: 0.35 }} transition={{ duration: 8, ease: "easeOut" }} />
      <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/40 to-black" />
      <div className="relative mx-auto max-w-3xl px-6 text-center">
        <motion.p {...line(0.3)} className="text-sm uppercase tracking-[0.3em] text-white/60">June 17, 2026 · UW–Madison</motion.p>
        <motion.h1 {...line(0.9)} className="mt-4 text-4xl font-semibold leading-tight md:text-6xl">
          A 4-foot pipe burst<br />under campus.
        </motion.h1>
        <motion.div {...line(1.9)} className="mt-10 grid grid-cols-3 gap-6">
          {[
            [<CountUp key="a" value={15.8} digits={1} prefix="$" suffix="M" />, "total cost"],
            [<CountUp key="b" value={34} />, "buildings lost cooling"],
            [<CountUp key="c" value={54} />, "days to fix"],
          ].map(([n, l], i) => (
            <div key={i}><div className="text-4xl font-semibold md:text-5xl">{n}</div><div className="mt-1 text-sm text-white/55">{l}</div></div>
          ))}
        </motion.div>
        <motion.p {...line(3.0)} className="mt-10 text-xl text-white/80">
          The same plant leaked in <span className="font-semibold text-white">1980</span>. The first sign back then was missing water.
        </motion.p>
        <motion.div {...line(3.8)} className="mt-10">
          <Button size="lg" onClick={onStart} className="h-12 rounded-full bg-white px-8 text-base text-black hover:bg-white/90">
            Replay it with LoopWatch →
          </Button>
        </motion.div>
      </div>
      <p className="absolute bottom-3 right-4 text-[10px] text-white/35">Photo: Richard Hurd, CC BY 2.0</p>
    </motion.div>
  )
}

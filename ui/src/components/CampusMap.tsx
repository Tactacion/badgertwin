import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import { Map as MLMap, Marker, type StyleSpecification } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Geo, Plan, State } from "@/lib/api"
import { fmt } from "@/lib/api"

// ---------------------------------------------------------------------------------------------
// Real UW–Madison campus: Esri satellite imagery + OpenFreeMap 3D buildings (both keyless).
// Our 50 buildings are their real OpenStreetMap footprints, lit by risk.
// Pipes carry particles: each dot moves at the simulated water speed; more water = more dots.
// ---------------------------------------------------------------------------------------------

export const RISK = { Normal: "#e7edf3", Watch: "#f5a524", Act: "#ff4d4f", Closed: "#ff4d4f" } as const
// Water dots go from deep blue (slow) to bright ice (fast), like wind on windy.com
function speedColor(fps: number) {
  const k = Math.max(0, Math.min(1, fps / 10))
  const r = Math.round(60 + 175 * k), g = Math.round(140 + 105 * k), b = 255
  return `rgba(${r},${g},${b},${0.55 + 0.45 * k})`
}
const CAMPUS = { center: [-89.4048, 43.0742] as [number, number], zoom: 15.15, pitch: 55, bearing: -12 }
const START = { center: [-89.41, 43.093] as [number, number], zoom: 12.6, pitch: 0, bearing: 0 }

const LANDMARKS = {
  type: "FeatureCollection",
  features: [
    ["Lake Mendota", -89.4105, 43.0825, "water"], ["Bascom Hill", -89.4043, 43.0751, "place"],
    ["Library Mall", -89.3988, 43.0756, "place"], ["Memorial Union", -89.4002, 43.0767, "place"],
    ["Camp Randall", -89.4127, 43.0700, "place"], ["Kohl Center", -89.3965, 43.0694, "place"],
    ["Lake Monona", -89.385, 43.064, "water"], ["Engineering", -89.4120, 43.0722, "place"],
  ].map(([name, lon, lat, kind]) => ({ type: "Feature", properties: { name, kind }, geometry: { type: "Point", coordinates: [lon, lat] } })),
}

function style(): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sky: { "sky-color": "#0a1220", "horizon-color": "#22324a", "fog-color": "#0a1220", "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.7, "fog-ground-blend": 0.35 } as any,
    sources: {
      sat: { type: "raster", tileSize: 256, maxzoom: 19,
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        attribution: "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community" },
      omt: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: "© OpenFreeMap © OpenStreetMap" },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#07090c" } },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": "#0b1620" } },
      { id: "park", type: "fill", source: "omt", "source-layer": "park", paint: { "fill-color": "#0c140f" } },
      { id: "roads", type: "line", source: "omt", "source-layer": "transportation", paint: { "line-color": "#1a1f26", "line-width": ["interpolate", ["linear"], ["zoom"], 13, 0.5, 17, 4] } },
      { id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": -0.35, "raster-brightness-max": 0.62, "raster-contrast": 0.08, "raster-fade-duration": 400 } },
      { id: "context-3d", type: "fill-extrusion", source: "omt", "source-layer": "building", minzoom: 14,
        paint: { "fill-extrusion-color": "#9aa4b1", "fill-extrusion-opacity": 0.28,
          "fill-extrusion-height": ["coalesce", ["get", "render_height"], 10],
          "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0] } },
    ],
  }
}

export interface MapHandle { flyTo: (lon: number, lat: number, zoom?: number) => void; flyToId: (id: string) => void; home: () => void; intro: () => void }
interface Props {
  geo: Geo | null; state: State | null; plan?: Plan | null; mode: "live" | "plan" | "fix"
  basemap: "satellite" | "dark"; startOnCampus?: boolean; selected?: string | null; onPick?: (what: { kind: "pipe" | "building"; id: string; name: string }) => void
}

type Particle = { pipe: number; s: number; jitter: number }
type Spray = { x: number; y: number; vx: number; vy: number; life: number }

export const CampusMap = forwardRef<MapHandle, Props>(function CampusMap({ geo, state, plan, mode, basemap, startOnCampus, selected, onPick }, ref) {
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const map = useRef<MLMap | null>(null)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState<{ x: number; y: number; html: string } | null>(null)
  const [hud, setHud] = useState({ lat: 0, lon: 0, zoom: 0, bearing: 0, pitch: 0 })
  const live = useRef({ state, plan, mode, geo })
  live.current = { state, plan, mode, geo }
  const orbit = useRef(true)
  const markers = useRef<Marker[]>([])

  // --------------------------------------------------------------- create map once
  useEffect(() => {
    const m = new MLMap({ container: box.current!, style: style(), ...(startOnCampus ? CAMPUS : START), maxPitch: 75, attributionControl: { compact: true } })
    map.current = m
    m.on("load", () => setReady(true))
    const upd = () => { const c = m.getCenter(); setHud({ lat: c.lat, lon: c.lng, zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch() }) }
    m.on("move", upd); upd()
    const stop = () => (orbit.current = false)
    m.on("mousedown", stop); m.on("touchstart", stop); m.on("wheel", stop)
    return () => m.remove()
  }, [])

  useImperativeHandle(ref, () => ({
    flyTo: (lon, lat, zoom = 16.6) => { orbit.current = false; map.current?.flyTo({ center: [lon, lat], zoom, pitch: 62, bearing: -30, duration: 2600, essential: true }) },
    flyToId: (id) => {
      const g = live.current.geo
      const b = g?.buildings.features.find((f) => f.properties.building_id === id)
      const pp = g?.pipes.features.find((f) => f.properties.pipe_id === id)
      const pts: number[][] = b ? b.geometry.coordinates[0] : pp ? pp.geometry.coordinates : []
      if (!pts.length) return
      const lon = pts.reduce((a, q) => a + q[0], 0) / pts.length, lat = pts.reduce((a, q) => a + q[1], 0) / pts.length
      orbit.current = false
      map.current?.flyTo({ center: [lon, lat], zoom: 17, pitch: 62, bearing: map.current.getBearing() - 25, duration: 2200, essential: true })
    },
    home: () => { orbit.current = true; map.current?.flyTo({ ...CAMPUS, duration: 2200, essential: true }) },
    intro: () => { orbit.current = true; map.current?.jumpTo(START); map.current?.flyTo({ ...CAMPUS, duration: 6500, curve: 1.6, essential: true }) },
  }))

  // --------------------------------------------------------------- our layers
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !geo || m.getSource("bt-b")) return
    m.addSource("bt-b", { type: "geojson", data: geo.buildings as any })
    m.addSource("bt-p", { type: "geojson", data: geo.pipes as any })
    m.addSource("bt-plants", { type: "geojson", data: geo.plants as any })
    m.addSource("bt-lm", { type: "geojson", data: LANDMARKS as any })
    const riskColor: any = ["match", ["coalesce", ["get", "label"], "Normal"], "Watch", RISK.Watch, "Act", RISK.Act, "Closed", RISK.Act, RISK.Normal]
    m.addLayer({ id: "bt-b-3d", type: "fill-extrusion", source: "bt-b",
      paint: { "fill-extrusion-color": riskColor, "fill-extrusion-opacity": 0.9,
        "fill-extrusion-height": ["+", ["get", "height"], 0.8], "fill-extrusion-vertical-gradient": true,
        "fill-extrusion-color-transition": { duration: 600 } } as any })
    m.addLayer({ id: "bt-b-sel", type: "line", source: "bt-b", filter: ["==", ["get", "building_id"], ""],
      paint: { "line-color": "#ffffff", "line-width": 3, "line-blur": 1.5 } })
    // pipes: soft glow + core. Width grows with the square root of flow (area ∝ flow).
    const width: any = ["interpolate", ["linear"], ["zoom"], 13, ["*", 0.45, ["get", "w"]], 17, ["*", 1.8, ["get", "w"]]]
    const glowWidth: any = ["interpolate", ["linear"], ["zoom"], 13, ["*", 1.4, ["get", "w"]], 17, ["*", 5, ["get", "w"]]]
    m.addLayer({ id: "bt-p-glow", type: "line", source: "bt-p", layout: { "line-cap": "round" },
      paint: { "line-color": riskColor, "line-opacity": 0.35, "line-blur": 6, "line-width": glowWidth } })
    m.addLayer({ id: "bt-p-core", type: "line", source: "bt-p", layout: { "line-cap": "round" },
      paint: { "line-color": riskColor, "line-opacity": ["case", ["==", ["get", "label"], "Normal"], 0.55, 0.95], "line-width": width } })
    m.addLayer({ id: "bt-p-closed", type: "line", source: "bt-p", filter: ["==", ["get", "label"], "Closed"],
      paint: { "line-color": "#07090c", "line-width": width, "line-dasharray": [1.2, 1.2] } })
    m.addLayer({ id: "bt-plants", type: "circle", source: "bt-plants",
      paint: { "circle-radius": 9, "circle-color": "#ffffff", "circle-stroke-color": "#07090c", "circle-stroke-width": 3, "circle-blur": 0.1 } })
    m.addLayer({ id: "bt-plants-label", type: "symbol", source: "bt-plants",
      layout: { "text-field": ["concat", ["get", "name"], " plant"], "text-font": ["Noto Sans Bold"], "text-size": 13, "text-offset": [0, 1.5], "text-anchor": "top" },
      paint: { "text-color": "#ffffff", "text-halo-color": "rgba(0,0,0,0.85)", "text-halo-width": 1.6 } })
    m.addLayer({ id: "bt-lm", type: "symbol", source: "bt-lm",
      layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Italic"], "text-size": ["match", ["get", "kind"], "water", 16, 12], "text-letter-spacing": 0.08, "text-transform": "uppercase" },
      paint: { "text-color": ["match", ["get", "kind"], "water", "rgba(160,210,255,0.75)", "rgba(255,255,255,0.7)"], "text-halo-color": "rgba(0,0,0,0.7)", "text-halo-width": 1.2 } })

    // hover + click
    const show = (e: any, html: string) => setHover({ x: e.point.x, y: e.point.y, html })
    m.on("mousemove", "bt-b-3d", (e) => {
      const p: any = e.features?.[0]?.properties
      const st = live.current.state?.buildings.find((b) => b.building_id === p.building_id)
      const pb = live.current.plan?.buildings.find((b) => b.building_id === p.building_id)
      m.getCanvas().style.cursor = "pointer"
      show(e, `<b>${p.name}</b><div class="opacity-70">${p.use} · ${fmt(p.tons)} tons at peak</div>` +
        (live.current.mode === "plan" && pb ? `<div>${pb.status === "closed" ? "Closed" : `${pb.served_pct}% cooled`}</div>` :
          st?.indoor_f ? `<div>${fmt(st.indoor_f, 1)} °F inside</div>` : ""))
    })
    m.on("mousemove", "bt-p-core", (e) => {
      const p: any = e.features?.[0]?.properties
      const st = live.current.state?.pipes.find((x) => x.pipe_id === p.pipe_id)
      m.getCanvas().style.cursor = "pointer"
      show(e, `<b>${p.pipe_id}</b><div class="opacity-70">${p.diameter}-inch · built ${p.install_year}</div>` +
        (st ? `<div>${fmt(st.flow_gpm)} gal/min · ${fmt(st.velocity_fps, 1)} ft/s</div>` : ""))
    })
    for (const l of ["bt-b-3d", "bt-p-core"]) m.on("mouseleave", l, () => { setHover(null); m.getCanvas().style.cursor = "" })
    m.on("click", "bt-b-3d", (e) => { const p: any = e.features?.[0]?.properties; onPick?.({ kind: "building", id: p.building_id, name: p.name }) })
    m.on("click", "bt-p-core", (e) => { const p: any = e.features?.[0]?.properties; onPick?.({ kind: "pipe", id: p.pipe_id, name: p.pipe_id }) })
  }, [ready, geo, onPick])

  // --------------------------------------------------------------- basemap toggle
  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    m.setLayoutProperty("sat", "visibility", basemap === "satellite" ? "visible" : "none")
    m.setPaintProperty("context-3d", "fill-extrusion-color", basemap === "satellite" ? "#c4ccd6" : "#2a3038")
    m.setPaintProperty("context-3d", "fill-extrusion-opacity", basemap === "satellite" ? 0.22 : 0.55)
  }, [ready, basemap])

  // --------------------------------------------------------------- push live data into layers
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !geo || !m.getSource("bt-b")) return
    const pl = Object.fromEntries((state?.pipes ?? []).map((p) => [p.pipe_id, p]))
    const bl = Object.fromEntries((state?.buildings ?? []).map((b) => [b.building_id, b.label]))
    const pb = Object.fromEntries((plan?.buildings ?? []).map((b) => [b.building_id, b]))
    ;(m.getSource("bt-p") as any).setData({
      ...geo.pipes, features: geo.pipes.features.map((f) => {
        const s = pl[f.properties.pipe_id]
        const label = mode === "plan" ? (f.properties.pipe_id === "CW-M01" ? "Closed" : "Normal") : mode === "fix" ? s?.health ?? "Normal" : s?.label ?? "Normal"
        return { ...f, properties: { ...f.properties, label, w: Math.max(1.2, Math.sqrt((s?.flow_gpm ?? 300) / 120)) } }
      }),
    })
    ;(m.getSource("bt-b") as any).setData({
      ...geo.buildings, features: geo.buildings.features.map((f) => {
        let label = bl[f.properties.building_id] ?? "Normal"
        if (mode === "plan") {
          const r = pb[f.properties.building_id]
          label = !r ? "Normal" : r.status === "closed" ? "Act" : r.served_pct < 100 ? "Watch" : "Normal"
        }
        return { ...f, properties: { ...f.properties, label } }
      }),
    })
  }, [ready, geo, state, plan, mode])

  // --------------------------------------------------------------- selection highlight
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !m.getLayer("bt-b-sel")) return
    m.setFilter("bt-b-sel", ["==", ["get", "building_id"], selected ?? ""])
    m.setPaintProperty("bt-p-core", "line-opacity", selected?.startsWith("CW-")
      ? ["case", ["==", ["get", "pipe_id"], selected], 1, 0.25] as any
      : ["case", ["==", ["get", "label"], "Normal"], 0.55, 0.95] as any)
  }, [ready, selected])

  // --------------------------------------------------------------- rented chiller markers
  useEffect(() => {
    markers.current.forEach((mk) => mk.remove())
    markers.current = []
    const m = map.current
    if (!ready || !m || mode !== "plan" || !plan) return
    for (const p of plan.placements) {
      const el = document.createElement("div")
      el.className = "bt-site"
      el.innerHTML = `<span class="bt-site-ring"></span><span class="bt-site-tag">${p.units}×${p.unit_tons}t</span>`
      markers.current.push(new Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(m))
    }
  }, [ready, plan, mode])

  // --------------------------------------------------------------- particles (the fun part)
  useEffect(() => {
    if (!ready || !geo) return
    const m = map.current!
    const cv = canvas.current!
    const ctx = cv.getContext("2d")!
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const pipes = geo.pipes.features.map((f) => ({ id: f.properties.pipe_id, d: f.properties.diameter, a: f.geometry.coordinates[0], b: f.geometry.coordinates[1],
      lenFt: lenFt(f.geometry.coordinates[0], f.geometry.coordinates[1]) }))
    const m01 = pipes.find((p) => p.id === "CW-M01")!
    const leakAt: [number, number] = [(m01.a[0] + m01.b[0]) / 2, (m01.a[1] + m01.b[1]) / 2]
    // Dots per pipe ∝ pipe size × length on screen (a steady stream); speed ∝ real velocity.
    const parts: Particle[] = []
    pipes.forEach((p, i) => {
      const n = Math.max(2, Math.round((p.lenFt / 180) * Math.sqrt(p.d / 6)))
      for (let k = 0; k < n; k++) parts.push({ pipe: i, s: Math.random(), jitter: (Math.random() - 0.5) * 0.6 })
    })
    const sprays: Spray[] = []
    const centroids = new Map(geo.buildings.features.map((f) => {
      const ring = f.geometry.coordinates[0] as number[][]
      return [f.properties.name, [ring.reduce((a, q) => a + q[0], 0) / ring.length, ring.reduce((a, q) => a + q[1], 0) / ring.length]] as const
    }))
    let raf = 0, last = performance.now(), ripple = 0
    const resize = () => {
      const r = cv.parentElement!.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1)
      cv.width = r.width * dpr; cv.height = r.height * dpr; cv.style.width = r.width + "px"; cv.style.height = r.height + "px"
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener("resize", resize)
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now
      const { state: st, mode: md } = live.current
      const flow = Object.fromEntries((st?.pipes ?? []).map((p) => [p.pipe_id, p]))
      if (orbit.current && !reduce && !m.isMoving()) m.setBearing(m.getBearing() + dt * 1.2)
      const W = cv.clientWidth, H = cv.clientHeight
      // Windy-style trails: fade the last frame instead of wiping it (wipe while the camera jumps)
      if (m.isMoving() && !orbit.current) ctx.clearRect(0, 0, W, H)
      else { ctx.globalCompositeOperation = "destination-out"; ctx.fillStyle = `rgba(0,0,0,${reduce ? 1 : 0.28})`; ctx.fillRect(0, 0, W, H) }
      ctx.globalCompositeOperation = "lighter"
      const scale = Math.pow(2, m.getZoom() - 15)
      const ends = pipes.map((p) => [m.project(p.a as any), m.project(p.b as any)])
      for (const pt of parts) {
        const p = pipes[pt.pipe], f = flow[p.id]
        if (!f || f.flow_gpm <= 0 || md === "plan" && p.id === "CW-M01") continue
        if (!reduce) pt.s += ((f.forward ? 1 : -1) * f.velocity_fps * 55 * dt) / p.lenFt
        pt.s -= Math.floor(pt.s)
        const [A, B] = ends[pt.pipe]
        const nx = -(B.y - A.y), ny = B.x - A.x, nl = Math.hypot(nx, ny) || 1
        const x = A.x + (B.x - A.x) * pt.s + (nx / nl) * pt.jitter * Math.sqrt(p.d / 6) * scale
        const y = A.y + (B.y - A.y) * pt.s + (ny / nl) * pt.jitter * Math.sqrt(p.d / 6) * scale
        if (x < -10 || y < -10 || x > W + 10 || y > H + 10) continue
        const r = (0.9 + Math.sqrt(p.d) / 6) * Math.min(1.6, Math.max(0.6, scale))
        ctx.fillStyle = speedColor(f.velocity_fps)
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill()
      }
      // leak: spray rate grows with the water being lost (log scale); burst is a fountain
      const leak = st?.leak
      const L = m.project(leakAt as any)
      if (leak && (leak.kind === "leak" || leak.kind === "burst") && md === "live") {
        const rate = leak.kind === "burst" ? 260 : 6 + 22 * Math.log10(1 + leak.excess_gal_per_day / 500)
        for (let k = 0; k < rate * dt; k++) {
          const a = Math.random() * Math.PI * 2, sp = (leak.kind === "burst" ? 40 + Math.random() * 90 : 8 + Math.random() * 22) * Math.max(0.6, scale)
          sprays.push({ x: L.x, y: L.y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - (leak.kind === "burst" ? 40 : 6), life: 1 })
        }
        ripple = (ripple + dt * 0.6) % 1
        for (let k = 0; k < 3; k++) {
          const q = (ripple + k / 3) % 1
          ctx.strokeStyle = `rgba(255,77,79,${(1 - q) * 0.8})`; ctx.lineWidth = 2
          ctx.beginPath(); ctx.arc(L.x, L.y, 6 + q * 70 * Math.max(0.6, scale), 0, Math.PI * 2); ctx.stroke()
        }
      }
      for (let i = sprays.length - 1; i >= 0; i--) {
        const s = sprays[i]
        s.x += s.vx * dt; s.y += s.vy * dt; s.vy += 60 * dt; s.life -= dt * 0.9
        if (s.life <= 0) { sprays.splice(i, 1); continue }
        ctx.fillStyle = `rgba(255,${120 + 80 * s.life},${110 * s.life},${s.life})`
        ctx.beginPath(); ctx.arc(s.x, s.y, 1.6, 0, Math.PI * 2); ctx.fill()
      }
      // kepler-style arcs: each rented chiller site → the buildings it cools
      if (md === "plan" && live.current.plan) {
        const dash = (now / 40) % 24
        for (const pl of live.current.plan.placements) {
          const A = m.project([pl.lon, pl.lat] as any)
          for (const fd of pl.feeds ?? []) {
            const c = centroids.get(fd.building)
            if (!c) continue
            const B = m.project(c as any)
            const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2 - Math.hypot(B.x - A.x, B.y - A.y) * 0.45
            ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 1.5 + Math.sqrt(fd.tons) / 12
            ctx.setLineDash([6, 6]); ctx.lineDashOffset = -dash
            ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.quadraticCurveTo(mx, my, B.x, B.y); ctx.stroke()
            ctx.setLineDash([])
          }
        }
      }
      ctx.globalCompositeOperation = "source-over"
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize) }
  }, [ready, geo])

  return (
    <div className="absolute inset-0">
      <div ref={box} className="h-full w-full" />
      <canvas ref={canvas} className="pointer-events-none absolute inset-0" />
      {/* Lattice-style frame + readout */}
      <div className="pointer-events-none absolute inset-4 z-[5]">
        {["left-0 top-16 border-l border-t", "right-0 top-16 border-r border-t", "left-0 bottom-24 border-l border-b", "right-0 bottom-24 border-r border-b"].map((c) => (
          <span key={c} className={`absolute size-5 border-white/35 ${c}`} />
        ))}
      </div>
      <div className="pointer-events-none absolute bottom-[34px] left-6 z-[5] text-left font-mono text-[10.5px] leading-relaxed text-white/55">
        <div>{hud.lat.toFixed(4)}°N {Math.abs(hud.lon).toFixed(4)}°W</div>
        <div>zoom {hud.zoom.toFixed(1)} · tilt {Math.round(hud.pitch)}° · heading {((Math.round(hud.bearing) % 360) + 360) % 360}°</div>
        <div className="mt-1.5 flex items-center gap-2">
          <span>water speed</span>
          <span className="h-1.5 w-24 rounded-full" style={{ background: `linear-gradient(90deg, ${speedColor(0)}, ${speedColor(5)}, ${speedColor(10)})` }} />
          <span>10+ ft/s</span>
        </div>
      </div>
      {hover && (
        <div className="pointer-events-none absolute z-20 rounded-lg border border-white/10 bg-black/75 px-3 py-2 text-xs text-white shadow-xl backdrop-blur"
          style={{ left: hover.x + 14, top: hover.y + 14 }} dangerouslySetInnerHTML={{ __html: hover.html }} />
      )}
    </div>
  )
})

function lenFt(a: number[], b: number[]) {
  const R = 20_902_231 // earth radius in feet
  const la1 = (a[1] * Math.PI) / 180, la2 = (b[1] * Math.PI) / 180, dla = la2 - la1, dlo = ((b[0] - a[0]) * Math.PI) / 180
  const h = Math.sin(dla / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dlo / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

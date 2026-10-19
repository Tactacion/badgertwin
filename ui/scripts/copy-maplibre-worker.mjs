// MapLibre 6 loads its web worker from `<bundle dir>/maplibre-gl-worker.mjs`; Vite doesn't copy it.
import { copyFileSync, mkdirSync } from "node:fs"
mkdirSync("public/assets", { recursive: true })
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) copyFileSync(`node_modules/maplibre-gl/dist/${f}`, `public/assets/${f}`)

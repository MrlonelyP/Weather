// MapLibre GL v6 runs its worker as an ES module (maplibre-gl-worker.mjs + maplibre-gl-shared.mjs).
// The bundler cannot rewrite that worker URL, so the two files are served from /public/maplibre
// and the map calls setWorkerUrl("/maplibre/maplibre-gl-worker.mjs"). Copied on every dev/build
// so they always match the installed package version.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "maplibre-gl", "dist");
const dest = join(root, "public", "maplibre");
mkdirSync(dest, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) copyFileSync(join(src, f), join(dest, f));
console.log("maplibre worker copied to public/maplibre");

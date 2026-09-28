/** Dashboard polling: reads our API (DB) only - it never makes a source API call. */
export const REFRESH_MS = Number(process.env.NEXT_PUBLIC_REFRESH_MS ?? 60_000);

/** Basemap only (no weather data, no key). */
export const MAP_STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/** Used when the basemap style cannot be loaded: our data layers still render on a plain background. */
export const FALLBACK_MAP_STYLE = {
  version: 8 as const,
  glyphs: "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
  sources: {},
  layers: [{ id: "background", type: "background" as const, paint: { "background-color": "#0b1c30" } }],
};
/** Latin/numeric map labels (basemap glyph sets have no Thai). */
export const LABEL_FONT = ["Open Sans Regular", "Noto Sans Regular"];

export const THAILAND_VIEW = { center: [100.8, 13.3] as [number, number], zoom: 5.2 };
export const THAILAND_BOUNDS: [[number, number], [number, number]] = [
  [96.5, 5.3],
  [106.2, 20.6],
];

/** MapLibre v6 worker (ES module) served from /public - see scripts/copy-maplibre-worker.mjs */
export const MAPLIBRE_WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

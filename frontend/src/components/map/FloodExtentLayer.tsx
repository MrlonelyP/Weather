"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { ensureSource, EMPTY_FC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "flood-extent";
const L_FILL = "flood-extent-fill";
const L_LINE = "flood-extent-line";

/** Satellite-detected flood polygons (GISTDA). Empty until the backend has data. */
export function FloodExtentLayer({ map, geojson, visible }: { map: MlMap; geojson: GeoJSON.FeatureCollection | null; visible: boolean }) {
  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({ id: L_FILL, type: "fill", source: SRC, paint: { "fill-color": "#2563eb", "fill-opacity": 0.45 } });
    map.addLayer({ id: L_LINE, type: "line", source: SRC, paint: { "line-color": "#60a5fa", "line-width": 1 } });
    return () => removeAll(map, [L_LINE, L_FILL], SRC);
  }, [map]);
  useEffect(() => setData(map, SRC, geojson ?? EMPTY_FC), [map, geojson]);
  useEffect(() => setVisible(map, [L_FILL, L_LINE], visible), [map, visible]);
  return null;
}

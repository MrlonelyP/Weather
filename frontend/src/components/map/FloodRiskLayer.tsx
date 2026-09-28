"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { ensureSource, EMPTY_FC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "flood-risk";
const L_FILL = "flood-risk-fill";

/**
 * System-assessed flood risk areas (experimental, never an official warning).
 * The backend does not provide areas yet, so the source stays empty.
 */
export function FloodRiskLayer({ map, geojson, visible }: { map: MlMap; geojson: GeoJSON.FeatureCollection | null; visible: boolean }) {
  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({
      id: L_FILL, type: "fill", source: SRC,
      paint: { "fill-color": ["coalesce", ["get", "color"], "#fb923c"], "fill-opacity": 0.25, "fill-outline-color": "#fb923c" },
    });
    return () => removeAll(map, [L_FILL], SRC);
  }, [map]);
  useEffect(() => setData(map, SRC, geojson ?? EMPTY_FC), [map, geojson]);
  useEffect(() => setVisible(map, [L_FILL], visible), [map, visible]);
  return null;
}

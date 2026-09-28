"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { LABEL_FONT } from "@/config/app";
import type { OfficialWarning } from "@/types/warning";
import { SEVERITY } from "@/utils/status";
import { ensureSource, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "warnings";
const L_FILL = "warnings-fill";
const L_LINE = "warnings-line";
const L_ICON = "warnings-icon";

/** Areas of ACTIVE official warnings that carry a polygon (e.g. TMD SIGMET). */
export function WarningLayer({ map, warnings, visible }: { map: MlMap; warnings: OfficialWarning[]; visible: boolean }) {
  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({ id: L_FILL, type: "fill", source: SRC, paint: { "fill-color": ["get", "color"], "fill-opacity": 0.12 } });
    map.addLayer({ id: L_LINE, type: "line", source: SRC, paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-dasharray": [2, 1.5] } });
    map.addLayer({
      id: L_ICON, type: "symbol", source: SRC,
      layout: { "icon-image": "triangle", "icon-size": 0.45, "text-field": ["get", "title"], "text-font": LABEL_FONT, "text-size": 11, "text-offset": [0, 1.4], "text-anchor": "top" },
      paint: { "icon-color": ["get", "color"], "text-color": "#e6eef7", "text-halo-color": "#071525", "text-halo-width": 1.2 },
    });
    return () => removeAll(map, [L_ICON, L_LINE, L_FILL], SRC);
  }, [map]);

  useEffect(() => {
    const features: GeoJSON.Feature[] = warnings
      .filter((w) => w.active && w.area_geojson)
      .map((w) => ({
        type: "Feature",
        geometry: w.area_geojson as GeoJSON.Polygon,
        properties: { title: `${w.agency_code} ${(w.type ?? "").toUpperCase().replace(/_/g, " ")}`, color: SEVERITY[w.severity].color },
      }));
    setData(map, SRC, { type: "FeatureCollection", features });
  }, [map, warnings]);

  useEffect(() => setVisible(map, [L_FILL, L_LINE, L_ICON], visible), [map, visible]);
  return null;
}

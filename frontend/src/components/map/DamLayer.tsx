"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { LABEL_FONT } from "@/config/app";
import type { Reservoir } from "@/types/water";
import { ensureSource, pointsFC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "dams";
const L_ICON = "dams-icon";

/** Dams with coordinates only (RID's API has none today, so nothing is drawn). */
export function DamLayer({ map, reservoirs, visible }: { map: MlMap; reservoirs: Reservoir[]; visible: boolean }) {
  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({
      id: L_ICON, type: "symbol", source: SRC,
      layout: { "icon-image": "dam", "icon-size": 0.5, "icon-allow-overlap": true, "text-field": ["get", "label"], "text-font": LABEL_FONT, "text-size": 11, "text-offset": [0, 1.3], "text-anchor": "top" },
      paint: {
        "icon-color": ["step", ["get", "pct"], "#38bdf8", 80, "#facc15", 100, "#ef4444"],
        "text-color": "#e6eef7", "text-halo-color": "#071525", "text-halo-width": 1.2,
      },
    });
    return () => removeAll(map, [L_ICON], SRC);
  }, [map]);
  useEffect(() => {
    setData(map, SRC, pointsFC(reservoirs, (r) => ({ pct: r.pct ?? 0, label: `${r.pct ?? "--"}%` })));
  }, [map, reservoirs]);
  useEffect(() => setVisible(map, [L_ICON], visible), [map, visible]);
  return null;
}

"use client";

import type { ExpressionSpecification, Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { LABEL_FONT } from "@/config/app";
import type { RainForecastPoint, RainPoint } from "@/types/weather";
import { rainColorExpression } from "@/utils/rainScale";
import { ensureSource, pointsFC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "rain";
const L_OBS = "rain-observed";
const L_FC = "rain-forecast";
const L_FC_LABEL = "rain-forecast-label";

/** Observed rain at gauges (small dots) or forecast rain at forecast points (large rings). */
export function RainLayer({ map, observed, forecast, mode, visible }: {
  map: MlMap;
  observed: RainPoint[];
  forecast: RainForecastPoint[];
  mode: "observed" | "forecast";
  visible: boolean;
}) {
  useEffect(() => {
    ensureSource(map, SRC);
    const color = rainColorExpression("v") as unknown as ExpressionSpecification;
    map.addLayer({
      id: L_OBS, type: "circle", source: SRC, filter: ["all", ["==", ["get", "kind"], "observed"], [">=", ["get", "v"], 0.1]],
      layout: { "circle-sort-key": ["get", "v"] },
      paint: {
        "circle-color": color,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 3, 10, 7],
        "circle-opacity": 0.85,
        "circle-blur": 0.15,
      },
    });
    map.addLayer({
      id: L_FC, type: "circle", source: SRC, filter: ["==", ["get", "kind"], "forecast"],
      paint: {
        "circle-color": color,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 9, 10, 22],
        "circle-opacity": 0.45,
        "circle-stroke-color": "#e6eef7",
        "circle-stroke-width": 1.2,
      },
    });
    map.addLayer({
      id: L_FC_LABEL, type: "symbol", source: SRC, filter: ["==", ["get", "kind"], "forecast"],
      layout: { "text-field": ["concat", ["to-string", ["get", "v"]], " mm"], "text-font": LABEL_FONT, "text-size": 11, "text-offset": [0, 1.8] },
      paint: { "text-color": "#e6eef7", "text-halo-color": "#071525", "text-halo-width": 1.2 },
    });
    return () => removeAll(map, [L_FC_LABEL, L_FC, L_OBS], SRC);
  }, [map]);

  useEffect(() => {
    const fc = mode === "observed"
      ? pointsFC(observed, (p) => ({ v: p.value_mm, kind: "observed" }))
      : pointsFC(forecast, (p) => ({ v: p.value_mm, kind: "forecast" }));
    setData(map, SRC, fc);
  }, [map, observed, forecast, mode]);

  useEffect(() => setVisible(map, [L_OBS, L_FC, L_FC_LABEL], visible), [map, visible]);
  return null;
}

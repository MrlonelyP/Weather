"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { LABEL_FONT } from "@/config/app";
import type { WeatherStationPoint } from "@/types/weather";
import { ensureSource, pointsFC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "weather-stations";
const L_ICON = "weather-stations-icon";

/** TMD synoptic stations with their latest observed temperature. */
export function WeatherStationLayer({ map, stations, visible }: { map: MlMap; stations: WeatherStationPoint[]; visible: boolean }) {
  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({
      id: L_ICON, type: "symbol", source: SRC,
      layout: {
        "icon-image": "cloud", "icon-size": 0.42, "icon-allow-overlap": true,
        "text-field": ["concat", ["to-string", ["get", "t"]], "°"], "text-font": LABEL_FONT, "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top",
      },
      paint: { "icon-color": "#cbd5e1", "text-color": "#e6eef7", "text-halo-color": "#071525", "text-halo-width": 1.2 },
    });
    return () => removeAll(map, [L_ICON], SRC);
  }, [map]);
  useEffect(() => {
    setData(map, SRC, pointsFC(stations.filter((s) => s.temperature_c !== null), (s) => ({ t: s.temperature_c ?? 0 })));
  }, [map, stations]);
  useEffect(() => setVisible(map, [L_ICON], visible), [map, visible]);
  return null;
}

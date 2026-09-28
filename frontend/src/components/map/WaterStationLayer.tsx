"use client";

import type { ExpressionSpecification, Map as MlMap, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { WaterStation } from "@/types/water";
import { WATER_STATUS } from "@/utils/status";
import { buildStationPopup } from "./popups";
import { ensureSource, pointsFC, removeAll, setData, setVisible } from "./mapUtils";

const SRC = "water-stations";
const L_CIRCLE = "water-stations-circle";
const L_ICON = "water-stations-icon";
const L_SELECTED = "water-stations-selected";

const colorExpr = [
  "match", ["get", "status"],
  ...Object.entries(WATER_STATUS).flatMap(([k, v]) => [k, v.color]),
  "#64748b",
] as unknown as ExpressionSpecification;

export function WaterStationLayer({ map, stations, visible, selected, onSelect }: {
  map: MlMap;
  stations: WaterStation[];
  visible: boolean;
  selected: string | null;
  onSelect: (code: string) => void;
}) {
  const byCode = useRef(new Map<string, WaterStation>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    ensureSource(map, SRC);
    map.addLayer({
      id: L_CIRCLE, type: "circle", source: SRC,
      layout: { "circle-sort-key": ["-", 10, ["get", "rank"]] },
      paint: {
        "circle-color": colorExpr,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["case", ["<=", ["get", "rank"], 1], 5.5, 4], 10,
          ["case", ["<=", ["get", "rank"], 1], 11, 9]],
        "circle-stroke-color": "#071525",
        "circle-stroke-width": 1.2,
        "circle-opacity": 0.95,
      },
    });
    map.addLayer({
      id: L_ICON, type: "symbol", source: SRC, minzoom: 8,
      layout: { "icon-image": "drop", "icon-size": 0.32, "icon-allow-overlap": true },
      paint: { "icon-color": "#071525" },
    });
    map.addLayer({
      id: L_SELECTED, type: "circle", source: SRC, filter: ["==", ["get", "code"], ""],
      paint: { "circle-radius": 14, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#e6eef7", "circle-stroke-width": 2 },
    });

    const click = (e: MapLayerMouseEvent) => {
      const code = e.features?.[0]?.properties?.code as string | undefined;
      const st = code ? byCode.current.get(code) : undefined;
      if (!st || st.lat === null || st.lon === null) return;
      import("maplibre-gl").then((ml) => {
        new ml.Popup({ maxWidth: "300px", offset: 10 })
          .setLngLat([st.lon as number, st.lat as number])
          .setDOMContent(buildStationPopup(st, () => onSelectRef.current(st.station_code)))
          .addTo(map);
      });
    };
    const enter = () => (map.getCanvas().style.cursor = "pointer");
    const leave = () => (map.getCanvas().style.cursor = "");
    map.on("click", L_CIRCLE, click);
    map.on("mouseenter", L_CIRCLE, enter);
    map.on("mouseleave", L_CIRCLE, leave);
    return () => {
      map.off("click", L_CIRCLE, click);
      map.off("mouseenter", L_CIRCLE, enter);
      map.off("mouseleave", L_CIRCLE, leave);
      removeAll(map, [L_SELECTED, L_ICON, L_CIRCLE], SRC);
    };
  }, [map]);

  useEffect(() => {
    byCode.current = new Map(stations.map((s) => [s.station_code, s]));
    setData(map, SRC, pointsFC(stations, (s) => ({ code: s.station_code, status: s.status, rank: WATER_STATUS[s.status].rank })));
  }, [map, stations]);

  useEffect(() => {
    if (map.getLayer(L_SELECTED)) map.setFilter(L_SELECTED, ["==", ["get", "code"], selected ?? ""]);
  }, [map, selected]);

  useEffect(() => setVisible(map, [L_CIRCLE, L_ICON, L_SELECTED], visible), [map, visible]);
  return null;
}

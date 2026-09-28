"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect } from "react";
import { alive } from "./mapUtils";

/**
 * Rivers/canals and admin boundaries come from the basemap itself (no extra data).
 * The toggles show/hide the matching basemap layers; rivers are tinted to stand out.
 */
export function BasemapLayers({ map, rivers, boundaries }: { map: MlMap; rivers: boolean; boundaries: boolean }) {
  useEffect(() => {
    if (!alive(map)) return;
    for (const layer of map.getStyle().layers ?? []) {
      const id = layer.id.toLowerCase();
      const isWater = /waterway|river|canal|stream/.test(id) && layer.type === "line";
      const isBoundary = /boundary|admin/.test(id);
      if (isWater) {
        map.setLayoutProperty(layer.id, "visibility", rivers ? "visible" : "none");
        try {
          map.setPaintProperty(layer.id, "line-color", "#2b6cb0");
        } catch {
          /* layer without line-color */
        }
      } else if (isBoundary) {
        map.setLayoutProperty(layer.id, "visibility", boundaries ? "visible" : "none");
      }
    }
  }, [map, rivers, boundaries]);
  return null;
}

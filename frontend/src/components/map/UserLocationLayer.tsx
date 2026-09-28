"use client";

import type { Map as MlMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";

/** Optional: the user's position (only when they ask for it). */
export function UserLocationLayer({ map, position }: { map: MlMap; position: { lat: number; lon: number } | null }) {
  const marker = useRef<Marker | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (!position) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    import("maplibre-gl").then((ml) => {
      if (cancelled) return;
      marker.current?.remove();
      const el = document.createElement("div");
      el.style.cssText = "width:16px;height:16px;border-radius:50%;background:#3097f3;border:3px solid #fff;box-shadow:0 0 0 6px rgba(48,151,243,.25)";
      el.setAttribute("aria-label", "ตำแหน่งของคุณ");
      marker.current = new ml.Marker({ element: el }).setLngLat([position.lon, position.lat]).addTo(map);
      map.flyTo({ center: [position.lon, position.lat], zoom: 11.5 });
    });
    return () => {
      cancelled = true;
    };
  }, [map, position]);
  useEffect(() => () => {
    marker.current?.remove();
  }, []);
  return null;
}

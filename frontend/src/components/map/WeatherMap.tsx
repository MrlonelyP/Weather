"use client";

import type { Map as MlMap } from "maplibre-gl";
import { LocateFixed, Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { FALLBACK_MAP_STYLE, MAP_STYLE_URL, MAPLIBRE_WORKER_URL, THAILAND_BOUNDS, THAILAND_VIEW } from "@/config/app";
import type { LayerId } from "@/config/layers";
import type { OfficialWarning } from "@/types/warning";
import type { Reservoir, WaterStation } from "@/types/water";
import type { RainForecastPoint, RainPoint, WeatherStationPoint } from "@/types/weather";
import { BasemapLayers } from "./BasemapLayers";
import { DamLayer } from "./DamLayer";
import { FloodExtentLayer } from "./FloodExtentLayer";
import { FloodRiskLayer } from "./FloodRiskLayer";
import { registerIcons } from "./icons";
import { RainLayer } from "./RainLayer";
import { UserLocationLayer } from "./UserLocationLayer";
import { WarningLayer } from "./WarningLayer";
import { WaterStationLayer } from "./WaterStationLayer";
import { WeatherStationLayer } from "./WeatherStationLayer";

export interface MapData {
  waterStations: WaterStation[];
  rainObserved: RainPoint[];
  rainForecast: RainForecastPoint[];
  rainMode: "observed" | "forecast";
  warnings: OfficialWarning[];
  floodExtent: GeoJSON.FeatureCollection | null;
  floodRisk: GeoJSON.FeatureCollection | null;
  reservoirs: Reservoir[];
  weatherStations: WeatherStationPoint[];
}

export interface FlyTarget {
  lat: number;
  lon: number;
  zoom?: number;
  bbox?: [number, number, number, number] | null;
  key: number;
}

/** MapLibre shell: basemap + our data layers. All data arrives as props from our API. */
export function WeatherMap({ data, layers, selected, onSelectStation, flyTo, userPosition, onLocate, children }: {
  data: MapData;
  layers: Record<LayerId, boolean>;
  selected: string | null;
  onSelectStation: (code: string) => void;
  flyTo: FlyTarget | null;
  userPosition: { lat: number; lon: number } | null;
  onLocate: () => void;
  children?: React.ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let instance: MlMap | null = null;
    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || !container.current) return;
      ml.setWorkerUrl(MAPLIBRE_WORKER_URL);
      const m = new ml.Map({
        container: container.current,
        style: MAP_STYLE_URL,
        center: THAILAND_VIEW.center,
        zoom: THAILAND_VIEW.zoom,
        maxBounds: [[90, 0], [112, 25]],
        attributionControl: { compact: true },
      });
      instance = m;
      // Ready as soon as the style is parsed; basemap tiles/sprites/glyphs keep loading after.
      m.once("style.load", () => {
        registerIcons(m);
        m.fitBounds(THAILAND_BOUNDS, { padding: 20, duration: 0 });
        setMap(m);
      });
      // Missing sprites, glyphs or tiles are not fatal. If the basemap style itself cannot be
      // loaded, switch to a plain background so the water data is still shown.
      let fellBack = false;
      m.on("error", (e) => {
        const url = String((e.error as { url?: string } | undefined)?.url ?? "");
        if (!fellBack && !m.isStyleLoaded() && url === MAP_STYLE_URL) {
          fellBack = true;
          setFailed("แผนที่พื้นฐานโหลดไม่สำเร็จ แสดงเฉพาะข้อมูลของระบบ");
          m.setStyle(FALLBACK_MAP_STYLE);
        }
      });
    });
    return () => {
      cancelled = true;
      setMap(null);
      instance?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map || !flyTo) return;
    if (flyTo.bbox) {
      map.fitBounds([[flyTo.bbox[0], flyTo.bbox[1]], [flyTo.bbox[2], flyTo.bbox[3]]], { padding: 80, maxZoom: 13 });
    } else {
      map.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: flyTo.zoom ?? 12 });
    }
  }, [map, flyTo]);

  return (
    <div className="relative h-full min-h-[420px] w-full overflow-hidden rounded-[var(--radius-card)] border border-line bg-bg-1">
      {/* inline style: maplibre's own (unlayered) CSS sets .maplibregl-map{position:relative},
          which would override a Tailwind utility and collapse the map to 0 px height */}
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      {!map && <div className="absolute inset-0 grid place-items-center text-[13px] text-muted">กำลังโหลดแผนที่…</div>}
      {failed && (
        <p className="absolute bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-md bg-bg-1/90 px-3 py-1 text-[11.5px] text-watch">{failed}</p>
      )}
      {map && (
        <>
          <BasemapLayers map={map} rivers={layers.river} boundaries={layers.boundaries} />
          <FloodExtentLayer map={map} geojson={data.floodExtent} visible={layers.floodExtent} />
          <FloodRiskLayer map={map} geojson={data.floodRisk} visible={layers.floodRisk} />
          <WarningLayer map={map} warnings={data.warnings} visible={layers.warning} />
          <RainLayer map={map} observed={data.rainObserved} forecast={data.rainForecast} mode={data.rainMode} visible={layers.rain} />
          <DamLayer map={map} reservoirs={data.reservoirs} visible={layers.dam} />
          <WeatherStationLayer map={map} stations={data.weatherStations} visible={layers.weatherStations} />
          <WaterStationLayer map={map} stations={data.waterStations} visible={layers.water} selected={selected} onSelect={onSelectStation} />
          <UserLocationLayer map={map} position={userPosition} />
        </>
      )}
      {/* overlays (layer control, time selector, legend) */}
      <div className="pointer-events-none absolute inset-0 p-3">{children}</div>
      <div className="absolute right-3 bottom-8 flex flex-col gap-1.5">
        {[
          { icon: Plus, label: "ซูมเข้า", on: () => map?.zoomIn() },
          { icon: Minus, label: "ซูมออก", on: () => map?.zoomOut() },
          { icon: LocateFixed, label: "ไปยังตำแหน่งของฉัน", on: onLocate },
        ].map(({ icon: Icon, label, on }) => (
          <button
            key={label}
            onClick={on}
            aria-label={label}
            title={label}
            className="grid size-9 place-items-center rounded-lg border border-line-strong bg-bg-1/92 text-ink shadow-lg hover:bg-bg-2"
          >
            <Icon className="size-4" />
          </button>
        ))}
      </div>
    </div>
  );
}

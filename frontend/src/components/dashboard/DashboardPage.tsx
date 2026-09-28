"use client";

import { useCallback, useMemo, useState } from "react";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { MapLayerControl } from "@/components/map/MapLayerControl";
import { MapTimeSelector, type MapMode, type MapTime } from "@/components/map/MapTimeSelector";
import { RainLegend } from "@/components/map/RainLegend";
import { WeatherMap, type FlyTarget } from "@/components/map/WeatherMap";
import { REFRESH_MS } from "@/config/app";
import { LAYERS, type LayerId } from "@/config/layers";
import { useGeolocation } from "@/hooks/useGeolocation";
import { usePolling } from "@/hooks/usePolling";
import { dashboardService } from "@/services/dashboard";
import { floodService } from "@/services/flood";
import { locationService } from "@/services/location";
import { newsService } from "@/services/news";
import { warningService } from "@/services/warning";
import { waterService } from "@/services/water";
import { weatherService } from "@/services/weather";
import type { SearchArea } from "@/types/search";
import { fmtTime } from "@/utils/format";
import { AlertPanel } from "./AlertPanel";
import { FloodRiskPanel } from "./FloodRiskPanel";
import { NearbyPanel } from "./NearbyPanel";
import { NewsPanel } from "./NewsPanel";
import { RainPanel } from "./RainPanel";
import { ReservoirPanel } from "./ReservoirPanel";
import { SettingsDrawer } from "./SettingsDrawer";
import { StationDetailDrawer } from "./StationDetailDrawer";
import { SummaryCards } from "./SummaryCards";
import { TidePanel } from "./TidePanel";
import { EMPTY_FILTER, WaterStationTable, type TableFilter } from "./WaterStationTable";
import { WatchListPanel } from "./WatchListPanel";
import { WeatherPanel } from "./WeatherPanel";

const SLOW = REFRESH_MS * 5;

/**
 * WATER FIRST: current levels, trends and the stations to watch come first;
 * weather explains what may happen next; location (optional) finds what matters.
 */
export function DashboardPage() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [layers, setLayers] = useState(() => Object.fromEntries(LAYERS.map((l) => [l.id, l.defaultOn])) as Record<LayerId, boolean>);
  const [mapTime, setMapTime] = useState<MapTime>("now");
  const [mapMode, setMapMode] = useState<MapMode>("observed");
  const [flyTo, setFlyTo] = useState<FlyTarget | null>(null);
  const [filter, setFilter] = useState<TableFilter>(EMPTY_FILTER);
  const [area, setArea] = useState("bangkok");
  const geo = useGeolocation();

  // --- data (our API only) --------------------------------------------------
  const summary = usePolling((s) => dashboardService.summary(s), [], REFRESH_MS);
  const sources = usePolling((s) => dashboardService.sourcesHealth(s), [], REFRESH_MS);
  const water = usePolling((s) => waterService.stations({ sort: "risk" }, s), [], REFRESH_MS);
  const filters = usePolling((s) => waterService.filters(s), [], SLOW);
  const warnings = usePolling((s) => warningService.list(s), [], REFRESH_MS);
  const reservoirs = usePolling((s) => waterService.reservoirs(s), [], SLOW);
  const tide = usePolling((s) => waterService.tide(s), [], SLOW);
  const floodExtent = usePolling((s) => floodService.extent(s), [], SLOW);
  const floodRisk = usePolling((s) => floodService.risk(s), [], SLOW);
  const news = usePolling((s) => newsService.list(s), [], SLOW);
  const locations = usePolling((s) => weatherService.locations(s), [], null);
  const rainWindow = mapTime === "now" ? "1h" : mapTime;
  const rainObs = usePolling((s) => weatherService.rainfall(rainWindow, s), [rainWindow], REFRESH_MS);
  const rainFc = usePolling(
    (s) => (mapMode === "forecast" ? weatherService.rainForecast(rainWindow, s) : Promise.resolve(null)),
    [mapMode, rainWindow], mapMode === "forecast" ? REFRESH_MS : null);
  const wStations = usePolling(
    (s) => (layers.weatherStations ? weatherService.stations(s) : Promise.resolve(null)), [layers.weatherStations], REFRESH_MS);
  const current = usePolling((s) => weatherService.current(area, s), [area], REFRESH_MS);
  const comparison = usePolling((s) => weatherService.comparison(area, s), [area], REFRESH_MS);
  const areaLoc = locations.data?.locations.find((l) => l.code === area);
  const areaNearby = usePolling(
    (s) => (areaLoc ? waterService.nearby(areaLoc.lat, areaLoc.lon, 10, s) : Promise.resolve(null)),
    [areaLoc?.code], REFRESH_MS);
  const userNearby = usePolling(
    (s) => (geo.position ? waterService.nearby(geo.position.lat, geo.position.lon, 10, s) : Promise.resolve(null)),
    [geo.position?.lat, geo.position?.lon], geo.position ? REFRESH_MS : null);
  const userAnalysis = usePolling(
    (s) => (geo.position ? locationService.analyze(geo.position.lat, geo.position.lon, s) : Promise.resolve(null)),
    [geo.position?.lat, geo.position?.lon], geo.position ? SLOW : null);

  // --- interactions ---------------------------------------------------------
  const fly = useCallback((t: Omit<FlyTarget, "key">) => setFlyTo({ ...t, key: Date.now() }), []);
  const selectStation = useCallback((code: string) => setSelected(code), []);
  const search = useMemo(() => ({
    onArea: (a: SearchArea) => a.center && fly({ lat: a.center.lat, lon: a.center.lon, bbox: a.bbox, zoom: 11 }),
    onStation: (code: string, lat: number | null, lon: number | null) => {
      if (lat !== null && lon !== null) fly({ lat, lon, zoom: 12 });
      setSelected(code);
    },
    onRiver: (name: string) => {
      setFilter({ ...EMPTY_FILTER, river: name });
      document.getElementById("water")?.scrollIntoView({ behavior: "smooth" });
    },
    onReservoir: () => document.getElementById("reservoirs")?.scrollIntoView({ behavior: "smooth" }),
    onPoint: (lat: number, lon: number) => fly({ lat, lon, zoom: 12 }),
  }), [fly]);

  const legendTitle = mapMode === "forecast"
    ? `ฝนคาดการณ์ ${rainWindow.replace("h", " ชม.")} ข้างหน้า (มม.)`
    : mapTime === "now" ? "ฝนชั่วโมงล่าสุด (มม./ชม.)" : `ฝนสะสม ${rainWindow.replace("h", " ชม.")} ที่ผ่านมา (มม.)`;
  const legendNote = mapMode === "forecast"
    ? rainFc.data?.note
    : [mapTime === "now" ? "เรดาร์ยังไม่เชื่อมต่อ: แสดงฝนรายชั่วโมงจากสถานีวัดฝน" : null, rainObs.data?.note].filter(Boolean).join(" · ");

  return (
    <div id="top" className="min-h-screen">
      <Sidebar sources={sources.data?.sources ?? null} sourcesAt={sources.data?.generated_at ?? null} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="xl:pl-[264px]">
        <Header
          activePublic={warnings.data?.active_public ?? null}
          activeAviation={warnings.data?.active_aviation ?? null}
          onMenu={() => setSidebarOpen(true)}
          onLocate={geo.locate}
          locating={geo.locating}
          onAlerts={() => document.getElementById("alerts")?.scrollIntoView({ behavior: "smooth" })}
          onSettings={() => setSettingsOpen(true)}
          search={search}
        />
        <main className="space-y-4 px-4 py-4 md:px-6">
          {geo.error && <p className="rounded-lg border border-watch/40 bg-watch/10 px-3 py-2 text-[12.5px] text-watch">{geo.error} (ใช้งานหน้านี้ได้ตามปกติโดยไม่ต้องใช้ตำแหน่ง)</p>}

          {/* 1-2. current levels and trends */}
          <SummaryCards summary={summary.data} water={water.data} />

          {/* 3-4. map of water stations + stations to watch + official warnings */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="h-[560px] 2xl:h-[640px]">
              <WeatherMap
                data={{
                  waterStations: water.data?.stations ?? [],
                  rainObserved: rainObs.data?.points ?? [],
                  rainForecast: rainFc.data?.points ?? [],
                  rainMode: mapMode,
                  warnings: warnings.data?.warnings ?? [],
                  floodExtent: floodExtent.data?.geojson ?? null,
                  floodRisk: null,
                  reservoirs: reservoirs.data?.reservoirs ?? [],
                  weatherStations: wStations.data?.stations ?? [],
                }}
                layers={layers}
                selected={selected}
                onSelectStation={selectStation}
                flyTo={flyTo}
                userPosition={geo.position}
                onLocate={geo.locate}
              >
                <div className="flex h-full flex-col justify-between">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <MapLayerControl visible={layers} onToggle={(id) => setLayers((l) => ({ ...l, [id]: !l[id] }))} />
                    <MapTimeSelector time={mapTime} mode={mapMode} onTime={setMapTime} onMode={setMapMode} />
                  </div>
                  <div className="hidden md:block"><RainLegend title={legendTitle} note={legendNote} /></div>
                </div>
              </WeatherMap>
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              {geo.position && <NearbyPanel data={userNearby.data} analysis={userAnalysis.data} onSelect={selectStation} onClose={geo.clear} />}
              <WatchListPanel data={water.data} onSelect={selectStation} />
              <div id="alerts"><AlertPanel data={warnings.data} /></div>
            </div>
          </div>

          {/* 3. full watch list with filters  |  5. dams  |  6. tide */}
          <div id="water" className="grid scroll-mt-20 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <WaterStationTable data={water.data} filters={filters.data} filter={filter} onFilter={setFilter} onSelect={selectStation} />
            <div className="flex min-w-0 flex-col gap-4">
              <div id="reservoirs"><ReservoirPanel data={reservoirs.data} /></div>
              <TidePanel data={tide.data} />
            </div>
          </div>

          {/* 7-8. rain now + forecast, and what it may mean for water levels  |  weather */}
          <div id="rain" className="grid scroll-mt-20 grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <RainPanel locations={locations.data?.locations ?? []} location={area} onLocation={setArea} data={comparison.data} nearby={areaNearby.data} />
            <div id="weather" className="min-w-0 scroll-mt-20">
              <WeatherPanel locations={locations.data?.locations ?? []} location={area} onLocation={setArea} data={current.data} />
            </div>
          </div>

          {/* 9. flood risk (system)  |  news (separate from official) */}
          <div id="risk" className="grid scroll-mt-20 grid-cols-1 gap-4 lg:grid-cols-2">
            <FloodRiskPanel risk={floodRisk.data} extent={floodExtent.data} />
            <div id="news" className="min-w-0 scroll-mt-20"><NewsPanel data={news.data} /></div>
          </div>

          <p className="pb-4 text-center text-[11.5px] text-muted">
            หน้าจออัปเดตจากระบบล่าสุด {fmtTime(water.refreshedAt?.toISOString())} น. (รีเฟรชทุก {Math.round(REFRESH_MS / 1000)} วินาที)
            · เวลาของข้อมูลต้นทางดูได้ในแต่ละส่วน · การประเมินโดยระบบไม่ใช่ประกาศทางราชการ
          </p>
        </main>
      </div>
      <StationDetailDrawer code={selected} onClose={() => setSelected(null)} />
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

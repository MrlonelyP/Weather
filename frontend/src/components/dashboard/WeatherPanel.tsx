"use client";

import { Cloud, CloudDrizzle, CloudRain, CloudSun, Droplets, Gauge, Sun, Thermometer, Wind, type LucideIcon } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import type { Condition, LocationRef, WeatherCurrent } from "@/types/weather";
import { fmtDayTime, fmtHour, fmtNum } from "@/utils/format";
import { LocationTabs } from "./LocationTabs";

const COND_ICON: Record<Condition["code"], LucideIcon> = {
  heavy_rain: CloudRain, moderate_rain: CloudRain, light_rain: CloudDrizzle, overcast: Cloud, partly_cloudy: CloudSun, clear: Sun,
};
const DIRS = ["เหนือ", "ตะวันออกเฉียงเหนือ", "ตะวันออก", "ตะวันออกเฉียงใต้", "ใต้", "ตะวันตกเฉียงใต้", "ตะวันตก", "ตะวันตกเฉียงเหนือ"];
const dirName = (deg: number | null) => (deg === null ? "" : `ลม${DIRS[Math.round(deg / 45) % 8]}`);

export function WeatherPanel({ locations, location, onLocation, data }: {
  locations: LocationRef[];
  location: string;
  onLocation: (c: string) => void;
  data: WeatherCurrent | null;
}) {
  const now = data?.forecast_now;
  const Icon = now?.condition ? COND_ICON[now.condition.code] : Cloud;
  const slots = (data?.hourly ?? []).filter((_, i) => i % 3 === 2).slice(0, 5);
  return (
    <Panel title="พยากรณ์อากาศรายพื้นที่" icon={CloudSun}
      action={<LocationTabs locations={locations} value={location} onChange={onLocation} />}
      footer={<FreshnessTag f={data?.freshness.forecast[0]} />}>
      {!data ? <LoadingRows rows={5} /> : !now ? (
        <EmptyState title="ยังไม่มีพยากรณ์สำหรับพื้นที่นี้" detail="ยังไม่มีรอบโมเดลที่ใหม่พอ (ภายใน 24 ชม.)" />
      ) : (
        <div className="grid gap-4 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <div>
            <div className="flex items-center gap-3">
              <Icon className="size-12 text-rain" aria-hidden />
              <div>
                <p className="font-[family-name:var(--font-display)] text-[34px] leading-none font-bold tabular">{fmtNum(now.temperature_c, 0)}°C</p>
                <p className="mt-1 text-[13px] text-ink-2">{now.condition?.label_th ?? "--"}</p>
              </div>
            </div>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
              <Row icon={Thermometer} k="รู้สึกเหมือน" v={`${fmtNum(now.feels_like_c, 0)}°C`} />
              <Row icon={Droplets} k="โอกาสฝน" v={`${fmtNum(now.rain_probability_pct, 0)}%${now.rain_probability_basis === "model_agreement" ? " (โมเดลเห็นตรงกัน)" : ""}`} />
              <Row icon={Droplets} k="ความชื้น" v={`${fmtNum(now.humidity_pct, 0)}%`} />
              <Row icon={Wind} k="ลม" v={`${fmtNum(now.wind_speed_kmh, 0)} กม./ชม. ${dirName(now.wind_direction_deg)}`} />
              <Row icon={Gauge} k="ความกดอากาศ" v={`${fmtNum(now.pressure_msl_hpa, 0)} hPa`} />
            </dl>
            <p className="mt-2 text-[11px] text-muted">พยากรณ์ของระบบ (consensus {now.n_models} โมเดล) · {data.observed ? `ตรวจวัดจริง ${data.observed.station_name} ${fmtNum(data.observed.temperature_c, 1)}°C เมื่อ ${fmtDayTime(data.observed.observed_at)}` : "ไม่มีค่าตรวจวัดใกล้เคียงใน 4 ชม."}</p>
          </div>
          <div className="grid grid-cols-5 gap-1.5 self-start rounded-xl border border-line bg-bg-1 p-2">
            {slots.map((h) => {
              const HIcon = h.condition ? COND_ICON[h.condition.code] : Cloud;
              return (
                <div key={h.time} className="flex flex-col items-center gap-1 py-1 text-center">
                  <span className="text-[11.5px] text-muted tabular">{fmtHour(h.time)}</span>
                  <HIcon className="size-6 text-rain" aria-label={h.condition?.label_th} />
                  <span className="text-[14px] font-semibold tabular">{fmtNum(h.temperature_c, 0)}°</span>
                  <span className="flex items-center gap-0.5 text-[11px] text-rain tabular"><Droplets className="size-3" />{fmtNum(h.rain_probability_pct, 0)}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Panel>
  );
}

function Row({ icon: Icon, k, v }: { icon: LucideIcon; k: string; v: string }) {
  return (
    <>
      <dt className="flex items-center gap-1.5 text-muted"><Icon className="size-3.5" />{k}</dt>
      <dd className="tabular text-ink">{v}</dd>
    </>
  );
}

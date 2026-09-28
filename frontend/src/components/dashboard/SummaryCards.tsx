import { ArrowDownRight, ArrowUpRight, CloudRain, Landmark, ShieldAlert, TrendingUp, Waves, type LucideIcon } from "lucide-react";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import type { Freshness } from "@/types/common";
import type { DashboardSummary } from "@/types/dashboard";
import type { WaterStationsResponse } from "@/types/water";
import { fmtNum, fmtSigned } from "@/utils/format";

interface CardProps {
  icon: LucideIcon;
  tone: string;
  label: string;
  value: string;
  unit?: string;
  change?: { text: string; up: boolean; bad: boolean } | null;
  changeNote?: string;
  support: string;
  freshness?: Freshness | null;
}

function Card({ icon: Icon, tone, label, value, unit, change, changeNote, support, freshness }: CardProps) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-[var(--radius-card)] border border-line bg-card px-4 py-3.5">
      <div className="flex items-start gap-3">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl" style={{ background: `${tone}22`, color: tone }}>
          <Icon className="size-6" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-[12.5px] text-ink-2">{label}</p>
          <p className="flex flex-wrap items-baseline gap-x-1.5 font-[family-name:var(--font-display)]">
            <span className="text-[28px] leading-tight font-bold tabular">{value}</span>
            {unit && <span className="text-[14px] font-semibold text-ink-2">{unit}</span>}
            {change && (
              <span className={`ml-1 inline-flex items-center text-[12.5px] font-semibold ${change.bad ? "text-warning" : "text-normal"}`}>
                {change.up ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
                {change.text}
              </span>
            )}
          </p>
        </div>
      </div>
      <p className="truncate text-[12px] text-muted" title={support}>{support}</p>
      {changeNote && !change && <p className="text-[11px] text-muted">{changeNote}</p>}
      {freshness !== undefined && <div className="mt-auto"><FreshnessTag f={freshness} compact /></div>}
    </div>
  );
}

/** Water first: critical stations, rising stations, dams, rain, then (system) flood risk. */
export function SummaryCards({ summary, water }: { summary: DashboardSummary | null; water: WaterStationsResponse | null }) {
  const counts = water?.counts;
  const rising = water?.stations.filter((s) => s.trend === "rising").length ?? null;
  const falling = water?.stations.filter((s) => s.trend === "falling").length ?? null;
  const fast = water?.stations.filter((s) => (s.rate_cm_per_h ?? 0) >= 5).length ?? null;
  const crit = summary?.critical_water;
  const res = summary?.reservoirs;
  const rain = summary?.rain_24h;
  const change = (v: number | null | undefined, unit: string, upIsBad: boolean) =>
    v === null || v === undefined ? null : { text: `${fmtSigned(v, unit === "%" ? 2 : 0)}${unit}`, up: v > 0, bad: upIsBad ? v > 0 : v < 0 };

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 wide:grid-cols-5">
      <Card icon={Waves} tone="#ef4444" label="สถานีระดับน้ำวิกฤต (ถึง/เกินตลิ่ง)"
        value={counts ? String(counts.CRITICAL) : "--"} unit="สถานี"
        change={change(crit?.change, "", true)} changeNote={crit?.change_basis}
        support={counts ? `เสี่ยงสูง ${counts.WARNING} · เฝ้าระวัง ${counts.WATCH} · จาก ${water?.stations.length} สถานี (ระบบประเมิน)` : "กำลังโหลดข้อมูล"}
        freshness={water?.freshness} />
      <Card icon={TrendingUp} tone="#fb923c" label="สถานีที่ระดับน้ำกำลังขึ้น"
        value={rising === null ? "--" : String(rising)} unit="สถานี"
        support={rising === null ? "กำลังโหลดข้อมูล" : `ขึ้นเร็ว ≥5 ซม./ชม. ${fast} · กำลังลด ${falling}`}
        freshness={water?.freshness} />
      <Card icon={Landmark} tone="#22c55e" label="เขื่อนขนาดใหญ่ (น้ำรวม)"
        value={fmtNum(res?.value, 1)} unit="%"
        change={change(res?.change, "%", true)} changeNote={res?.change_basis}
        support={res ? `${res.count} เขื่อน · เทียบปริมาณน้ำเก็บกัก (RID)` : "กำลังโหลดข้อมูล"}
        freshness={res?.freshness} />
      <Card icon={CloudRain} tone="#38bdf8" label="ฝนสะสม 24 ชม. สูงสุด"
        value={fmtNum(rain?.value, 1)} unit="มม."
        change={change(rain?.change, "", true)} changeNote={rain?.change_basis}
        support={rain?.station ? `${rain.station} ${rain.province ?? ""}` : "กำลังโหลดข้อมูล"}
        freshness={rain?.freshness} />
      <Card icon={ShieldAlert} tone="#94a3b8" label="พื้นที่เสี่ยงน้ำท่วม (ระบบประเมิน)"
        value={summary?.flood_risk.available ? fmtNum(summary.flood_risk.value, 0) : "--"} unit="พื้นที่"
        support={summary ? (summary.flood_risk.available ? "การประเมินโดยระบบ ไม่ใช่ประกาศทางราชการ" : summary.flood_risk.reason) : "กำลังโหลดข้อมูล"} />
    </div>
  );
}

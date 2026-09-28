import type { Freshness } from "@/types/common";
import { fmtAge, fmtTime } from "@/utils/format";
import { FRESHNESS } from "@/utils/status";

const BASIS_LABEL: Record<Freshness["basis"], string> = {
  data: "ข้อมูล ณ",
  model_run: "รอบโมเดล",
  data_date: "รายงานวันที่",
  fetch: "ดึงเมื่อ",
};

/** "ข้อมูล ณ 11:00 · ดึง 11:07 · อายุ 7 นาที" + status dot. Never just "real-time". */
export function FreshnessTag({ f, compact = false }: { f: Freshness | null | undefined; compact?: boolean }) {
  if (!f) return <span className="text-[11.5px] text-muted">ยังไม่มีข้อมูลความสด</span>;
  const s = FRESHNESS[f.status];
  const sourceTime = f.basis === "fetch" ? f.fetched_at : f.source_time;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11.5px] text-muted" title={f.note ?? undefined}>
      <span className="inline-flex items-center gap-1 font-semibold" style={{ color: s.color }}>
        <span className="size-1.5 rounded-full" style={{ background: s.color }} />
        {s.label}
      </span>
      {sourceTime && (
        <span>
          {BASIS_LABEL[f.basis]} {fmtTime(sourceTime)}
        </span>
      )}
      {!compact && f.fetched_at && f.basis !== "fetch" && <span>· ดึง {fmtTime(f.fetched_at)}</span>}
      {f.age_minutes !== null && <span>· อายุ {fmtAge(f.age_minutes)}</span>}
    </span>
  );
}

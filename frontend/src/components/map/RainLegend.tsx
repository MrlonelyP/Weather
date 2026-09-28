import { RAIN_BINS } from "@/utils/rainScale";
import { WATER_STATUS } from "@/utils/status";

export function RainLegend({ title, note }: { title: string; note?: string | null }) {
  return (
    <div className="pointer-events-auto w-[200px] rounded-xl border border-line-strong bg-bg-1/92 p-3 shadow-xl backdrop-blur">
      <p className="mb-2 text-[12px] font-semibold">{title}</p>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-1">
        {[...RAIN_BINS].reverse().map((b) => (
          <li key={b.label} className="flex items-center gap-2 text-[11.5px] text-ink-2">
            <span className="h-3 w-5 rounded-sm" style={{ background: b.color }} />
            {b.label}
          </li>
        ))}
      </ul>
      <p className="mt-3 mb-1.5 text-[12px] font-semibold">สถานีวัดน้ำ (ระบบประเมิน)</p>
      <ul className="grid grid-cols-2 gap-1">
        {(["NORMAL", "WATCH", "WARNING", "CRITICAL"] as const).map((k) => (
          <li key={k} className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
            <span className="size-2.5 rounded-full" style={{ background: WATER_STATUS[k].color }} />
            {WATER_STATUS[k].label}
          </li>
        ))}
      </ul>
      {note && <p className="mt-2 text-[10.5px] leading-snug text-muted">{note}</p>}
    </div>
  );
}

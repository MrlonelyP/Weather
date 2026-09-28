import { CloudRain } from "lucide-react";
import type { ForecastImpact } from "@/types/water";
import { IMPACT } from "@/utils/status";

/** "Will the coming rain raise the water?" - qualitative, never a number. */
export function ImpactBlock({ impact, title = "ฝนที่คาดการณ์จะทำให้น้ำขึ้นไหม" }: { impact: ForecastImpact | null | undefined; title?: string }) {
  if (!impact) return null;
  const c = IMPACT[impact.outlook].color;
  return (
    <div className="rounded-xl border p-3.5" style={{ borderColor: `${c}55`, background: `${c}10` }}>
      <p className="flex items-center gap-2 text-[12px] font-semibold text-ink-2"><CloudRain className="size-4" style={{ color: c }} />{title}</p>
      <p className="mt-1 font-[family-name:var(--font-display)] text-[16px] font-semibold" style={{ color: c }}>{impact.label_th}</p>
      {impact.reasons.length > 0 && (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-2">
          {impact.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted">
        {impact.disclaimer}
        {impact.forecast_point ? ` · ฝนคาดการณ์จากจุด ${impact.forecast_point.name_th} (ห่าง ${impact.forecast_point.distance_km} กม.)` : ""}
        {" · ยังไม่มีการพยากรณ์ตัวเลขระดับน้ำ"}
      </p>
    </div>
  );
}

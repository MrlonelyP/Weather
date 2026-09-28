import { ArrowDown, ArrowRight, ArrowUp, Minus } from "lucide-react";
import type { Trend } from "@/types/water";
import { fmtSigned } from "@/utils/format";
import { TREND, trendKey } from "@/utils/status";

export function TrendCell({ trend, rate }: { trend: Trend; rate: number | null }) {
  const t = TREND[trendKey(trend)];
  const Icon = trend === "rising" ? ArrowUp : trend === "falling" ? ArrowDown : trend === "steady" ? ArrowRight : Minus;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap tabular" style={{ color: t.color }} title={t.label}>
      <Icon className="size-3.5" aria-hidden />
      <span className="text-[12px]">{rate === null ? t.label : `${fmtSigned(rate, 1)} ซม./ชม.`}</span>
    </span>
  );
}

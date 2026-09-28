import type { WaterStatus } from "@/types/water";
import { WATER_STATUS } from "@/utils/status";

export function StatusBadge({ status, size = "sm" }: { status: WaterStatus; size?: "sm" | "md" }) {
  const s = WATER_STATUS[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full font-semibold ${
        size === "md" ? "px-3 py-1 text-[13px]" : "px-2 py-0.5 text-[11.5px]"
      }`}
      style={{ color: s.color, background: `${s.color}22`, boxShadow: `inset 0 0 0 1px ${s.color}55` }}
    >
      <span className="size-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

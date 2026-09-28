import { Landmark } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import type { ReservoirsResponse } from "@/types/water";
import { fmtNum, fmtSigned } from "@/utils/format";

const barColor = (p: number) => (p >= 100 ? "#ef4444" : p >= 90 ? "#fb923c" : p >= 80 ? "#facc15" : "#38bdf8");

export function ReservoirPanel({ data }: { data: ReservoirsResponse | null }) {
  return (
    <Panel title="เขื่อนและอ่างเก็บน้ำขนาดใหญ่" icon={Landmark}
      action={<span className="text-[12px] text-ink-2">รวม <b className="tabular">{fmtNum(data?.total_pct, 1)}%</b> {data?.total_pct_change !== null && data?.total_pct_change !== undefined && <span className="text-muted">({fmtSigned(data.total_pct_change, 2)})</span>}</span>}
      footer={<div className="space-y-0.5"><FreshnessTag f={data?.freshness} /><p className="text-[11px] text-muted">% เทียบปริมาณน้ำเก็บกัก (กรมชลประทาน) · {data?.coordinates_note}</p></div>}>
      {!data ? <LoadingRows rows={5} /> : data.reservoirs.length === 0 ? <EmptyState title="ยังไม่มีข้อมูลเขื่อน" /> : (
        <ul className="scroll-thin max-h-[360px] space-y-2.5 overflow-y-auto px-4 py-3">
          {data.reservoirs.map((r) => (
            <li key={r.reservoir_code} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
              <span className="truncate text-[13px]">{r.name}</span>
              <span className="text-right text-[13px] font-semibold tabular" style={{ color: barColor(r.pct ?? 0) }}>
                {fmtNum(r.pct, 1)}% <span className="text-[11px] font-normal text-muted">{r.pct_change !== null ? fmtSigned(r.pct_change, 2) : ""}</span>
              </span>
              <div className="col-span-2 h-1.5 overflow-hidden rounded-full bg-bg-2">
                <div className="h-full rounded-full" style={{ width: `${Math.min(r.pct ?? 0, 100)}%`, background: barColor(r.pct ?? 0) }} />
              </div>
              <span className="col-span-2 text-[11px] text-muted tabular">
                น้ำ {fmtNum(r.volume_mcm, 0)} ล้าน ลบ.ม. · เข้า {fmtNum(r.inflow_mcm_day, 2)} · ระบาย {fmtNum(r.outflow_mcm_day, 2)} ล้าน ลบ.ม./วัน
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

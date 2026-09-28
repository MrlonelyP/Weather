import { ShieldAlert } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import type { FloodExtentResponse, FloodRiskResponse } from "@/types/flood";

/** Wording: "การประเมินความเสี่ยงโดยระบบ" - never an official warning or evacuation order. */
export function FloodRiskPanel({ risk, extent }: { risk: FloodRiskResponse | null; extent: FloodExtentResponse | null }) {
  return (
    <Panel title="ความเสี่ยงน้ำท่วม (การประเมินโดยระบบ)" icon={ShieldAlert}>
      {!risk ? <LoadingRows rows={2} /> : (
        <div className="space-y-2 p-4">
          {!risk.available && <EmptyState icon={ShieldAlert} title="ยังไม่เปิดใช้การประเมินความเสี่ยง" detail={risk.reason} />}
          <p className="text-[11.5px] text-muted">{risk.disclaimer}</p>
          <p className="text-[11.5px] text-muted">พื้นที่น้ำท่วมจากดาวเทียม: {extent ? (extent.available ? `${extent.geojson.features.length} พื้นที่` : extent.reason) : "กำลังโหลด"}</p>
        </div>
      )}
    </Panel>
  );
}

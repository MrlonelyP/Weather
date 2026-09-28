import { Waves } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import type { TideResponse } from "@/types/water";

export function TidePanel({ data }: { data: TideResponse | null }) {
  return (
    <Panel title="น้ำทะเล / น้ำหนุน" icon={Waves}>
      {!data ? <LoadingRows rows={2} /> : !data.available ? (
        <EmptyState icon={Waves} title="ยังไม่มีข้อมูลระดับน้ำทะเล" detail={data.reason} />
      ) : (
        <EmptyState title="มีข้อมูลแล้ว" />
      )}
    </Panel>
  );
}

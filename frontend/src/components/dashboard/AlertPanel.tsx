"use client";

import { AlertTriangle, ChevronRight, Info, Siren, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import type { OfficialWarning, Severity, WarningsResponse } from "@/types/warning";
import { fmtDateTime, fmtDayTime } from "@/utils/format";
import { SEVERITY } from "@/utils/status";

const ICON: Record<Severity, LucideIcon> = { critical: Siren, warning: AlertTriangle, watch: AlertTriangle, info: Info };

/** Official warnings only (always with the issuing agency). News is a separate panel. */
export function AlertPanel({ data }: { data: WarningsResponse | null }) {
  const [open, setOpen] = useState<OfficialWarning | null>(null);
  const items = data?.warnings ?? [];
  return (
    <Panel title="ประกาศเตือนภัยล่าสุด (ทางการ)" icon={Siren}
      action={<span className="text-[11.5px] text-muted">48 ชม. ล่าสุด</span>}
      footer={<FreshnessTag f={data?.freshness} />}>
      {!data ? <LoadingRows rows={4} /> : items.length === 0 ? (
        <EmptyState title="ไม่มีประกาศจากหน่วยงานในช่วง 48 ชม." />
      ) : (
        <ul className="scroll-thin max-h-[330px] divide-y divide-line overflow-y-auto">
          {items.map((w) => {
            const s = SEVERITY[w.severity];
            const Icon = ICON[w.severity];
            return (
              <li key={w.id}>
                <button onClick={() => setOpen(w)} className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-bg-2 ${w.active ? "" : "opacity-60"}`}>
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: s.bg, color: s.color }}><Icon className="size-5" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[13.5px] font-semibold text-ink">{w.title}</span>
                      <span className="rounded px-1.5 py-0.5 text-[10.5px] font-semibold" style={{ background: s.bg, color: s.color }}>{s.label}</span>
                      {!w.active && <span className="rounded bg-bg-2 px-1.5 py-0.5 text-[10.5px] text-muted">หมดอายุ/ยกเลิก</span>}
                    </span>
                    <span className="block text-[12px] text-ink-2">{w.area_text ?? "ไม่ระบุพื้นที่"}</span>
                    <span className="block text-[11.5px] text-muted">{fmtDayTime(w.issued_at)} · {w.agency_name}</span>
                  </span>
                  <ChevronRight className="mt-2 size-4 shrink-0 text-muted" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {open && (
        <Drawer open onClose={() => setOpen(null)} title={<div><p className="font-[family-name:var(--font-display)] text-[16px] font-semibold">{open.title}</p><p className="text-[12px] text-muted">{open.agency_name} · ประกาศทางการ</p></div>}>
          <div className="space-y-3 p-5 text-[13px]">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
              <dt className="text-muted">ประเภท</dt><dd>{open.type_label}</dd>
              <dt className="text-muted">ระดับ (จัดตามประเภท)</dt><dd style={{ color: SEVERITY[open.severity].color }}>{SEVERITY[open.severity].label}</dd>
              <dt className="text-muted">พื้นที่</dt><dd>{open.area_text ?? "--"}</dd>
              <dt className="text-muted">ออกประกาศ</dt><dd>{fmtDateTime(open.issued_at)}</dd>
              <dt className="text-muted">มีผล</dt><dd>{open.valid_from ? `${fmtDayTime(open.valid_from)} – ${fmtDayTime(open.valid_to)}` : "--"}</dd>
              <dt className="text-muted">สถานะ</dt><dd>{open.active ? "มีผลอยู่" : "หมดอายุ/ยกเลิก"}</dd>
            </dl>
            <div>
              <p className="mb-1 text-muted">ข้อความต้นฉบับ ({open.bulletin_header})</p>
              <pre className="overflow-x-auto rounded-lg border border-line bg-bg-0 p-3 font-[family-name:var(--font-mono)] text-[12px] whitespace-pre-wrap text-ink-2">{open.body}</pre>
            </div>
            <p className="text-[11.5px] text-muted">{data?.note}</p>
          </div>
        </Drawer>
      )}
    </Panel>
  );
}

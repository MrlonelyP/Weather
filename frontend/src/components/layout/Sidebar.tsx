"use client";

import {
  AlertTriangle, CloudRain, CloudSun, FileText, History, Home, Info, Waves, X,
  type LucideIcon,
} from "lucide-react";
import type { SourceHealth } from "@/types/dashboard";
import { fmtDateTime } from "@/utils/format";
import { FRESHNESS } from "@/utils/status";

interface NavItem {
  label: string;
  icon: LucideIcon;
  href?: string;
  soon?: boolean;
}

const NAV: NavItem[] = [
  { label: "หน้าแรก", icon: Home, href: "#top" },
  { label: "ระดับน้ำและเขื่อน", icon: Waves, href: "#water" },
  { label: "ฝนและเรดาร์", icon: CloudRain, href: "#rain" },
  { label: "พยากรณ์อากาศ", icon: CloudSun, href: "#weather" },
  { label: "ความเสี่ยงน้ำท่วม", icon: AlertTriangle, href: "#risk" },
  { label: "รายงานและข่าว", icon: FileText, href: "#news" },
  { label: "ข้อมูลย้อนหลัง", icon: History, soon: true },
  { label: "เกี่ยวกับระบบ", icon: Info, soon: true },
];

export function Sidebar({ sources, sourcesAt, open, onClose }: {
  sources: SourceHealth[] | null;
  sourcesAt: string | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {open && <button className="fixed inset-0 z-30 bg-black/40 xl:hidden" aria-label="ปิดเมนู" onClick={onClose} />}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[264px] flex-col border-r border-line bg-bg-1 transition-transform xl:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-start justify-between gap-2 px-5 pt-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#3097f3] to-[#1e5fa8]">
              <Waves className="size-6 text-white" aria-hidden />
            </div>
            <div className="leading-tight">
              <p className="font-[family-name:var(--font-display)] text-[15px] font-bold">พยากรณ์อากาศและ<br />เตือนภัยน้ำท่วมประเทศไทย</p>
              <p className="mt-0.5 text-[11px] text-muted">Thailand Weather &amp; Flood Platform</p>
            </div>
          </div>
          <button className="rounded p-1 text-muted xl:hidden" onClick={onClose} aria-label="ปิดเมนู"><X className="size-5" /></button>
        </div>

        <nav className="space-y-1 px-3" aria-label="เมนูหลัก">
          {NAV.map((item, i) => {
            const Icon = item.icon;
            const cls = `flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[14px] ${
              i === 0 ? "bg-primary font-semibold text-white" : item.soon ? "cursor-not-allowed text-muted/70" : "text-ink-2 hover:bg-bg-2 hover:text-ink"
            }`;
            return item.soon ? (
              <span key={item.label} className={cls} aria-disabled="true" title="ยังไม่เปิดใช้งาน">
                <Icon className="size-[18px]" aria-hidden />{item.label}<span className="ml-auto text-[10.5px]">เร็ว ๆ นี้</span>
              </span>
            ) : (
              <a key={item.label} href={item.href} className={cls} onClick={onClose}>
                <Icon className="size-[18px]" aria-hidden />{item.label}
              </a>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-line px-5 py-4">
          <p className="mb-2 text-[12.5px] font-semibold text-ink-2">สถานะข้อมูล</p>
          {!sources ? (
            <p className="text-[12px] text-muted">กำลังตรวจสอบ…</p>
          ) : (
            <ul className="space-y-1.5">
              {sources.map((s) => {
                const f = FRESHNESS[s.status];
                return (
                  <li key={s.source} className="flex items-center justify-between gap-2 text-[12px]">
                    <span className="flex min-w-0 items-center gap-2 text-ink-2">
                      <span className="size-2 shrink-0 rounded-full" style={{ background: f.color }} />
                      <span className="truncate" title={s.label}>{s.label}</span>
                    </span>
                    <span className="shrink-0 text-right" style={{ color: f.color }} title={s.age_text ? `อายุข้อมูล ${s.age_text}` : undefined}>
                      {f.label}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-3 text-[11px] text-muted">ตรวจสอบล่าสุด<br />{fmtDateTime(sourcesAt)}</p>
        </div>
      </aside>
    </>
  );
}

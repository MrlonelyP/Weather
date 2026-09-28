"use client";

import { AlertTriangle, Bell, LocateFixed, Menu, Settings, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { SearchBox, type SearchActions } from "./SearchBox";

export function Header({ activePublic, activeAviation, onMenu, onLocate, locating, onAlerts, onSettings, search }: {
  activePublic: number | null;
  activeAviation: number | null;
  onMenu: () => void;
  onLocate: () => void;
  locating: boolean;
  onAlerts: () => void;
  onSettings: () => void;
  search: SearchActions;
}) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const clock = now
    ? `${new Intl.DateTimeFormat("th-TH", { timeZone: "Asia/Bangkok", day: "numeric", month: "long", year: "numeric" }).format(now)} ${new Intl.DateTimeFormat("th-TH", { timeZone: "Asia/Bangkok", hour: "2-digit", minute: "2-digit" }).format(now)} น.`
    : "";

  return (
    <header className="sticky top-0 z-20 flex flex-wrap items-center gap-3 border-b border-line bg-bg-0/95 px-4 py-3 backdrop-blur md:px-6">
      <button onClick={onMenu} className="rounded-lg p-2 text-ink-2 hover:bg-bg-2 xl:hidden" aria-label="เปิดเมนู">
        <Menu className="size-5" />
      </button>
      <div className="order-3 flex w-full items-center gap-2 md:order-none md:w-auto md:flex-1">
        <SearchBox {...search} />
        <button
          onClick={onLocate}
          className="grid size-11 shrink-0 place-items-center rounded-xl border border-line-strong bg-bg-1 text-ink-2 hover:text-ink"
          aria-label="ใช้ตำแหน่งของฉัน" title="ใช้ตำแหน่งของฉัน (ไม่บังคับ)"
        >
          <LocateFixed className={`size-[18px] ${locating ? "animate-pulse text-primary" : ""}`} />
        </button>
      </div>
      <div className="ml-auto flex items-center gap-2 md:gap-3">
        <span className="hidden text-[13px] text-ink-2 lg:inline tabular" suppressHydrationWarning>{clock}</span>
        {activePublic === null ? (
          <span className="rounded-xl border border-line px-3 py-2 text-[12.5px] text-muted">กำลังตรวจประกาศ…</span>
        ) : activePublic > 0 ? (
          <button onClick={onAlerts} className="flex items-center gap-2 rounded-xl border border-critical/50 bg-critical/15 px-3 py-2 text-[13px] font-semibold text-critical">
            <AlertTriangle className="size-4" />มีประกาศเตือนภัย {activePublic} รายการ
          </button>
        ) : (
          <button onClick={onAlerts} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-[12.5px] text-ink-2"
            title={activeAviation ? `SIGMET (การบิน) ที่มีผลอยู่ ${activeAviation} รายการ` : undefined}>
            <ShieldCheck className="size-4 text-normal" />ไม่มีประกาศเตือนภัยในขณะนี้
          </button>
        )}
        <button onClick={onAlerts} className="rounded-lg p-2 text-ink-2 hover:bg-bg-2" aria-label="การแจ้งเตือน"><Bell className="size-5" /></button>
        <button onClick={onSettings} className="rounded-lg p-2 text-ink-2 hover:bg-bg-2" aria-label="ตั้งค่าและข้อมูลระบบ"><Settings className="size-5" /></button>
      </div>
    </header>
  );
}

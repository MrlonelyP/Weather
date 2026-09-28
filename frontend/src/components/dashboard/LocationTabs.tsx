"use client";

import type { LocationRef } from "@/types/weather";

export function LocationTabs({ locations, value, onChange }: { locations: LocationRef[]; value: string; onChange: (c: string) => void }) {
  return (
    <div role="tablist" aria-label="เลือกพื้นที่" className="scroll-thin flex gap-1 overflow-x-auto">
      {locations.map((l) => (
        <button key={l.code} role="tab" aria-selected={l.code === value} onClick={() => onChange(l.code)}
          className={`shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium ${l.code === value ? "bg-primary text-white" : "bg-bg-1 text-ink-2 hover:bg-bg-2"}`}>
          {l.name_th ?? l.name_en}
        </button>
      ))}
    </div>
  );
}

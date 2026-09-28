"use client";

import { Layers, ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { LAYERS, type LayerId } from "@/config/layers";

export function MapLayerControl({ visible, onToggle }: {
  visible: Record<LayerId, boolean>;
  onToggle: (id: LayerId) => void;
}) {
  const [open, setOpen] = useState(true);
  // on narrower screens start collapsed so the map itself stays visible
  useEffect(() => {
    if (window.innerWidth < 1600) setOpen(false);
  }, []);
  return (
    <div className="pointer-events-auto w-[248px] rounded-xl border border-line-strong bg-bg-1/92 shadow-xl backdrop-blur">
      <button
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-[13px] font-semibold"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2"><Layers className="size-4 text-primary" />แสดงข้อมูลบนแผนที่</span>
        <ChevronDown className={`size-4 text-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul className="space-y-0.5 px-2 pb-2">
          {LAYERS.map((l) => (
            <li key={l.id}>
              <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-1.5 py-1 hover:bg-bg-2">
                <input
                  type="checkbox"
                  checked={visible[l.id]}
                  onChange={() => onToggle(l.id)}
                  className="mt-0.5 size-4 accent-[#3097f3]"
                />
                <span className="leading-tight">
                  <span className="block text-[12.5px] text-ink">{l.label}</span>
                  {l.unavailableReason && <span className="block text-[11px] text-muted">{l.unavailableReason}</span>}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

/** Right-side drawer for details (station, alert). Esc closes. */
export function Drawer({ open, title, onClose, children, width = 520 }: {
  open: boolean;
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button className="absolute inset-0 bg-black/45" aria-label="ปิด" onClick={onClose} />
      <div
        className="relative flex h-full w-full flex-col border-l border-line-strong bg-bg-1 shadow-2xl"
        style={{ maxWidth: width }}
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">{title}</div>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-bg-2 hover:text-ink" aria-label="ปิด">
            <X className="size-5" />
          </button>
        </header>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

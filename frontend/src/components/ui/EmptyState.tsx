import type { LucideIcon } from "lucide-react";

export function EmptyState({ icon: Icon, title, detail }: { icon?: LucideIcon; title: string; detail?: string | null }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
      {Icon && <Icon className="size-6 text-muted" aria-hidden />}
      <p className="text-[13.5px] font-medium text-ink-2">{title}</p>
      {detail && <p className="max-w-sm text-[12px] leading-relaxed text-muted">{detail}</p>}
    </div>
  );
}

export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" aria-busy="true" aria-label="กำลังโหลดข้อมูล">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-bg-2" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p className="px-4 py-2 text-[12px] text-warning">โหลดข้อมูลไม่สำเร็จ: {error.message}</p>;
}

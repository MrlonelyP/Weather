import type { LucideIcon } from "lucide-react";

interface PanelProps {
  title: string;
  icon?: LucideIcon;
  action?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

/** Card container used by every dashboard block. */
export function Panel({ title, icon: Icon, action, footer, className = "", bodyClassName = "", children }: PanelProps) {
  return (
    <section className={`flex min-w-0 flex-col rounded-[var(--radius-card)] border border-line bg-card ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-line px-4 py-3">
        <h2 className="flex min-w-0 items-center gap-2 font-[family-name:var(--font-display)] text-[15px] font-semibold text-ink">
          {Icon && <Icon className="size-4 shrink-0 text-primary" aria-hidden />}
          <span className="truncate">{title}</span>
        </h2>
        {action && <div className="min-w-0 max-w-full">{action}</div>}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
      {footer && <footer className="border-t border-line px-4 py-2">{footer}</footer>}
    </section>
  );
}

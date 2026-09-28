"use client";

interface SegmentedProps<T extends string> {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
  ariaLabel: string;
}

export function Segmented<T extends string>({ value, options, onChange, size = "sm", ariaLabel }: SegmentedProps<T>) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="inline-flex flex-wrap rounded-lg border border-line bg-bg-1 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md font-medium transition-colors ${size === "md" ? "px-3 py-1.5 text-[13px]" : "px-2.5 py-1 text-[12px]"} ${
            o.value === value ? "bg-primary text-white" : "text-ink-2 hover:bg-bg-2"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Rain legend (mm/h): light blue -> blue -> green -> yellow -> orange -> red -> purple. */
export const RAIN_BINS: { min: number; label: string; color: string }[] = [
  { min: 0.1, label: "0.1 – 1", color: "#7dd3fc" },
  { min: 1, label: "1 – 5", color: "#3b82f6" },
  { min: 5, label: "5 – 10", color: "#22c55e" },
  { min: 10, label: "10 – 20", color: "#facc15" },
  { min: 20, label: "20 – 50", color: "#fb923c" },
  { min: 50, label: "50 – 100", color: "#ef4444" },
  { min: 100, label: "> 100", color: "#c026d3" },
];

/** MapLibre `step` expression over the given numeric property. */
export function rainColorExpression(prop: string): unknown[] {
  const expr: unknown[] = ["step", ["get", prop], "rgba(0,0,0,0)"];
  for (const bin of RAIN_BINS) expr.push(bin.min, bin.color);
  return expr;
}

export function rainColor(mm: number): string {
  let color = "transparent";
  for (const bin of RAIN_BINS) if (mm >= bin.min) color = bin.color;
  return color;
}

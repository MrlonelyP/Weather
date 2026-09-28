"use client";

import type { StationDetail } from "@/types/water";
import { useMemo } from "react";
import { chartTheme, EChart } from "./EChart";

/**
 * Observed water level with reference lines (bank / warning / critical).
 * A future water-level forecast would be drawn as a separate dashed series;
 * none exists yet, so only observations are plotted.
 */
export function WaterLevelChart({ detail }: { detail: StationDetail }) {
  const option = useMemo(() => {
    const data = detail.series.map((p) => [p.time, p.level_m]);
    const refs = [
      { v: detail.levels.bank_m, name: "ระดับตลิ่ง", color: "#ef4444" },
      { v: detail.levels.critical_m, name: "ระดับวิกฤต", color: "#fb923c" },
      { v: detail.levels.warning_m, name: "ระดับเฝ้าระวัง", color: "#facc15" },
    ].filter((r) => r.v !== null);
    const values = [...detail.series.map((p) => p.level_m), ...refs.map((r) => r.v as number)];
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 1;
    const pad = Math.max((max - min) * 0.15, 0.1);
    return {
      animation: false,
      grid: { left: 44, right: 16, top: 16, bottom: 28 },
      tooltip: {
        trigger: "axis",
        ...chartTheme.tooltip,
        valueFormatter: (v: number) => `${v.toFixed(2)} ม.`,
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: chartTheme.axis } },
        axisLabel: { color: chartTheme.text, fontSize: 11, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: +(min - pad).toFixed(2),
        max: +(max + pad).toFixed(2),
        name: "ม.รทก.",
        nameTextStyle: { color: chartTheme.text, fontSize: 11 },
        axisLabel: { color: chartTheme.text, fontSize: 11 },
        splitLine: { lineStyle: { color: chartTheme.grid } },
      },
      series: [
        {
          name: "ระดับน้ำ (ตรวจวัด)",
          type: "line",
          data,
          // sparse history (station only recently collected): show the points themselves
          showSymbol: data.length <= 48,
          symbolSize: 5,
          itemStyle: { color: "#38bdf8" },
          lineStyle: { color: "#38bdf8", width: 2 },
          areaStyle: { color: "rgba(56,189,248,0.10)" },
          markLine: {
            symbol: "none",
            silent: true,
            data: refs.map((r) => ({
              yAxis: r.v,
              name: r.name,
              lineStyle: { color: r.color, type: "dashed", width: 1.5 },
              label: { formatter: `${r.name} ${(r.v as number).toFixed(2)}`, color: r.color, fontSize: 11, position: "insideEndTop" },
            })),
          },
        },
      ],
    };
  }, [detail]);

  return <EChart option={option} height={230} ariaLabel={`กราฟระดับน้ำ ${detail.name ?? ""}`} />;
}

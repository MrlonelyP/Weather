"use client";

import type { RainComparison } from "@/types/weather";
import { fmtHour } from "@/utils/format";
import { useMemo } from "react";
import { chartTheme, EChart } from "./EChart";

const MODEL_COLORS: Record<string, string> = { ECMWF: "#3b82f6", GFS: "#22c55e", JMA: "#ef4444" };

/**
 * Observed (bars, left of NOW) vs ECMWF / GFS / JMA and our consensus (lines, right of NOW).
 * The NOW marker splits observed from forecast.
 */
export function RainComparisonChart({ data }: { data: RainComparison }) {
  const option = useMemo(() => {
    const hour0 = new Date(data.hour0).getTime();
    const hours: number[] = [];
    for (let h = -24; h <= 24; h++) hours.push(hour0 + h * 3600_000);
    const cat = hours.map((t) => new Date(t).toISOString());
    const idx = new Map(hours.map((t, i) => [t, i]));
    const place = (pts: { time: string; v: number | null }[]) => {
      const arr: (number | null)[] = hours.map(() => null);
      for (const p of pts) {
        const i = idx.get(new Date(p.time).getTime());
        if (i !== undefined) arr[i] = p.v;
      }
      return arr;
    };
    const observed = place(data.observed.series.map((p) => ({ time: p.time, v: p.mean_mm })));
    const nowIdx = idx.get(hour0) ?? 24;
    const series: unknown[] = [
      {
        name: "ตรวจวัดจริง",
        type: "bar",
        data: observed,
        barMaxWidth: 10,
        itemStyle: { color: "#38bdf8", borderRadius: [2, 2, 0, 0] },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: "#e6eef7", type: "dashed", width: 1.2 },
          label: { formatter: "ปัจจุบัน", color: "#e6eef7", fontSize: 11 },
          data: [{ xAxis: nowIdx }],
        },
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(48,151,243,0.05)" },
          label: { color: chartTheme.text, fontSize: 11, position: "insideTop" },
          data: [
            [{ name: "ตรวจวัด", xAxis: 0 }, { xAxis: nowIdx }],
          ],
        },
      },
    ];
    for (const [model, pts] of Object.entries(data.models)) {
      series.push({
        name: model,
        type: "line",
        data: place(pts.map((p) => ({ time: p.time, v: p.mm }))),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: MODEL_COLORS[model] ?? "#a78bfa", width: 1.6 },
        itemStyle: { color: MODEL_COLORS[model] ?? "#a78bfa" },
      });
    }
    series.push({
      name: "พยากรณ์ของระบบ (consensus)",
      type: "line",
      data: place(data.consensus.map((p) => ({ time: p.time, v: p.mm }))),
      showSymbol: false,
      lineStyle: { color: "#f8fafc", width: 2.4, type: "dashed" },
      itemStyle: { color: "#f8fafc" },
    });
    return {
      animation: false,
      grid: { left: 40, right: 12, top: 34, bottom: 28 },
      legend: { top: 0, textStyle: { color: chartTheme.text, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: {
        trigger: "axis",
        ...chartTheme.tooltip,
        valueFormatter: (v: number | null) => (v === null || v === undefined ? "--" : `${v.toFixed(1)} มม.`),
      },
      xAxis: {
        type: "category",
        data: cat,
        axisLine: { lineStyle: { color: chartTheme.axis } },
        axisLabel: { color: chartTheme.text, fontSize: 11, interval: 2, formatter: (v: string) => fmtHour(v).slice(0, 2) },
      },
      yAxis: {
        type: "value",
        name: "มม./ชม.",
        nameTextStyle: { color: chartTheme.text, fontSize: 11 },
        axisLabel: { color: chartTheme.text, fontSize: 11 },
        splitLine: { lineStyle: { color: chartTheme.grid } },
      },
      series,
    };
  }, [data]);

  return <EChart option={option} height={250} ariaLabel="กราฟเปรียบเทียบฝนตรวจวัดกับฝนคาดการณ์" />;
}

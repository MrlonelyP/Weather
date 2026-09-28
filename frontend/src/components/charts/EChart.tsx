"use client";

import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent,
  MarkAreaComponent, CanvasRenderer]);

/** Minimal ECharts wrapper: init once, update options, resize with the container. */
export function EChart({ option, height = 240, ariaLabel }: { option: EChartsCoreOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />;
}

/** Shared dark styling for all charts. */
export const chartTheme = {
  text: "#8298b0",
  grid: "rgba(120,170,220,0.12)",
  axis: "rgba(120,170,220,0.3)",
  tooltip: {
    backgroundColor: "#0d2238",
    borderColor: "rgba(120,170,220,0.3)",
    textStyle: { color: "#e6eef7", fontFamily: "IBM Plex Sans Thai, sans-serif", fontSize: 12 },
  },
};

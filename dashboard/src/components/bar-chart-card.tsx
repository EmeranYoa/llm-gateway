"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/** Length of the bar animation of the first render, in milliseconds. */
const ANIMATION_MS = 600;

/**
 * True during the first render and its animation, false afterwards: charts
 * animate when the page opens, not on every auto-refresh.
 */
export function useAnimateOnce(durationMs = ANIMATION_MS): boolean {
  const [animate, setAnimate] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setAnimate(false), durationMs + 100);
    return () => clearTimeout(timer);
  }, [durationMs]);
  return animate;
}

/** One bar of the chart: its axis label, its tooltip label, and a value per series. */
export type ChartPoint = {
  label: string;
  tooltipLabel: string;
  [series: string]: string | number;
};

export type ChartSeries = {
  /** Key of the value in each `ChartPoint`. */
  key: string;
  /** Name in the legend and the tooltip. */
  name: string;
  color: string;
};

type BarChartCardProps = {
  title: string;
  data: ChartPoint[];
  series: ChartSeries[];
  /** Formats the values of the tooltip (see `src/lib/format.ts`). */
  formatValue: (value: number) => string;
  /** Formats the ticks of the value axis. Default: `formatValue`. */
  formatTick?: (value: number) => string;
  /** A line under the title, e.g. "One bar per UTC day." */
  note?: string;
  /** True for counts: the axis then has whole numbers only. */
  integer?: boolean;
};

/**
 * A titled bar chart of a time series, with a hover tooltip. Several series
 * are drawn side by side on one axis, with a legend.
 */
export function BarChartCard({
  title,
  data,
  series,
  formatValue,
  formatTick = formatValue,
  note,
  integer = false,
}: BarChartCardProps) {
  const animate = useAnimateOnce();

  return (
    <figure className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <figcaption className="mb-3">
        <span className="text-sm font-medium text-slate-700">{title}</span>
        {note && <span className="block text-xs text-slate-600">{note}</span>}
      </figcaption>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="#e2e8f0" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={{ stroke: "#cbd5e1" }}
              tick={{ fontSize: 11, fill: "#475569" }}
              minTickGap={12}
            />
            <YAxis
              allowDecimals={!integer}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: "#475569" }}
              tickFormatter={(value: number) => formatTick(value)}
              width={64}
            />
            <Tooltip
              cursor={{ fill: "#f1f5f9" }}
              labelFormatter={(_, payload) =>
                (payload?.[0]?.payload as ChartPoint | undefined)
                  ?.tooltipLabel ?? ""
              }
              formatter={(value) => formatValue(Number(value))}
            />
            {series.length > 1 && (
              <Legend
                iconType="square"
                itemSorter={null} // keep the order of `series`
                wrapperStyle={{ fontSize: 12 }}
              />
            )}
            {series.map((item) => (
              <Bar
                key={item.key}
                dataKey={item.key}
                name={item.name}
                fill={item.color}
                radius={[4, 4, 0, 0]}
                maxBarSize={24}
                isAnimationActive={animate}
                animationDuration={ANIMATION_MS}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

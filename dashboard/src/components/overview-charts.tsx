"use client";

import type { SeriesPoint } from "@/api/client";
import { useBrowserTimeZone } from "@/lib/browser-hooks";
import {
  formatBucket,
  formatCount,
  formatDateTime,
  formatMoney,
  formatMoneyTick,
} from "@/lib/format";
import type { Period } from "@/lib/period";

import { BarChartCard, type ChartPoint } from "./bar-chart-card";

const BLUE = "#0284c7"; // Tailwind sky-600
const RED = "#dc2626"; // Tailwind red-600

/** The note under each chart: what one bar covers, and in which time zone. */
export function bucketNote(period: Period, timeZone: string): string {
  return period === "24h"
    ? `One bar per hour, times in ${timeZone}.`
    : "One bar per UTC day.";
}

function toChartPoints(
  series: SeriesPoint[],
  period: Period,
  timeZone: string,
): ChartPoint[] {
  return series.map((point) => ({
    label: formatBucket(point.start, period, timeZone),
    tooltipLabel:
      period === "24h"
        ? formatDateTime(point.start, timeZone)
        : `${formatBucket(point.start, period, timeZone)} (UTC day)`,
    requests: point.requests,
    failed: point.failed,
    cost_usd: point.cost_usd,
    cache_hits: point.cache_hits,
  }));
}

/** The three charts of the overview: requests and failed, cost, cache hits. */
export function OverviewCharts({
  series,
  period,
}: {
  series: SeriesPoint[];
  period: Period;
}) {
  const timeZone = useBrowserTimeZone();
  const data = toChartPoints(series, period, timeZone);
  const note = bucketNote(period, timeZone);

  return (
    <section aria-label="Charts" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-wide text-slate-700 uppercase">
        Over time
      </h2>
      <BarChartCard
        title="Requests and failed requests"
        note={note}
        data={data}
        series={[
          { key: "requests", name: "Requests", color: BLUE },
          { key: "failed", name: "Failed", color: RED },
        ]}
        formatValue={formatCount}
        integer
      />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <BarChartCard
          title="Cost (USD)"
          note={note}
          data={data}
          series={[{ key: "cost_usd", name: "Cost", color: BLUE }]}
          formatValue={formatMoney}
          formatTick={formatMoneyTick}
        />
        <BarChartCard
          title="Cache hits"
          note={note}
          data={data}
          series={[{ key: "cache_hits", name: "Cache hits", color: BLUE }]}
          formatValue={formatCount}
          integer
        />
      </div>
    </section>
  );
}

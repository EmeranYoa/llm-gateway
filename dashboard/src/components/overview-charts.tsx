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
import { useLocale } from "@/lib/i18n/client";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";
import type { Period } from "@/lib/period";

import { BarChartCard, type ChartPoint } from "./bar-chart-card";

const BLUE = "#0284c7"; // Tailwind sky-600
const RED = "#dc2626"; // Tailwind red-600

/** The note under each chart: what one bar covers, and in which time zone. */
export function bucketNote(
  locale: Locale,
  period: Period,
  timeZone: string,
): string {
  const t = getTranslator(locale);
  return period === "24h"
    ? t("charts.hourNote", { timeZone })
    : t("charts.dayNote");
}

function toChartPoints(
  locale: Locale,
  series: SeriesPoint[],
  period: Period,
  timeZone: string,
): ChartPoint[] {
  const t = getTranslator(locale);
  return series.map((point) => ({
    label: formatBucket(locale, point.start, period, timeZone),
    tooltipLabel:
      period === "24h"
        ? formatDateTime(locale, point.start, timeZone)
        : t("charts.utcDay", {
            day: formatBucket(locale, point.start, period, timeZone),
          }),
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
  const locale = useLocale();
  const t = getTranslator(locale);
  const data = toChartPoints(locale, series, period, timeZone);
  const count = (value: number) => formatCount(locale, value);
  const note = bucketNote(locale, period, timeZone);

  return (
    <section aria-label={t("charts.label")} className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-wide text-slate-700 uppercase">
        {t("charts.title")}
      </h2>
      <BarChartCard
        title={t("charts.requestsTitle")}
        note={note}
        data={data}
        series={[
          { key: "requests", name: t("charts.requests"), color: BLUE },
          { key: "failed", name: t("charts.failed"), color: RED },
        ]}
        formatValue={count}
        integer
      />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <BarChartCard
          title={t("charts.costTitle")}
          note={note}
          data={data}
          series={[{ key: "cost_usd", name: t("charts.cost"), color: BLUE }]}
          formatValue={(value) => formatMoney(locale, value)}
          formatTick={(value) => formatMoneyTick(locale, value)}
        />
        <BarChartCard
          title={t("charts.cacheHitsTitle")}
          note={note}
          data={data}
          series={[
            { key: "cache_hits", name: t("charts.cacheHits"), color: BLUE },
          ]}
          formatValue={count}
          integer
        />
      </div>
    </section>
  );
}

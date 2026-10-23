import type { Overview } from "@/api/client";
import {
  formatCount,
  formatDuration,
  formatMoney,
  formatRate,
} from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

import { StatCard } from "./stat-card";

function FigureGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title}>
      <h2 className="mb-2 text-sm font-semibold tracking-wide text-slate-700 uppercase">
        {title}
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {children}
      </div>
    </section>
  );
}

/** The key figures of an overview, in four groups: traffic, speed, cost, cache. */
export function OverviewFigures({
  overview,
  locale,
}: {
  overview: Overview;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  const {
    latency_ms: latency,
    time_to_first_token_ms: firstToken,
    unpriced_requests: unpriced,
  } = overview;

  return (
    <div className="flex flex-col gap-6">
      <FigureGroup title={t("overview.groups.traffic")}>
        <StatCard
          locale={locale}
          label={t("overview.requests")}
          value={formatCount(locale, overview.requests)}
          definition={t("definitions.requests")}
          detail={t("overview.answered", { count: overview.answered })}
        />
        <StatCard
          locale={locale}
          label={t("overview.errorRate")}
          value={formatRate(locale, overview.error_rate)}
          definition={t("definitions.errorRate")}
          detail={t("overview.errorDetail", {
            failed: t("overview.failed", { count: overview.failed }),
            clientErrors: t("overview.clientErrors", {
              count: overview.client_error,
            }),
            cancelled: t("overview.cancelled", { count: overview.cancelled }),
          })}
        />
        <StatCard
          locale={locale}
          label={t("overview.fallbackRate")}
          value={formatRate(locale, overview.fallback_rate)}
          definition={t("definitions.fallbackRate")}
        />
      </FigureGroup>

      <FigureGroup title={t("overview.groups.speed")}>
        <StatCard
          locale={locale}
          label={t("overview.latency")}
          value={formatDuration(locale, latency.p50)}
          definition={t("definitions.latency")}
          detail={t("overview.p95", {
            value: formatDuration(locale, latency.p95),
          })}
        />
        <StatCard
          locale={locale}
          label={t("overview.timeToFirstToken")}
          value={formatDuration(locale, firstToken.p50)}
          definition={t("definitions.timeToFirstToken")}
          detail={t("overview.timeToFirstTokenDetail", {
            value: formatDuration(locale, firstToken.p95),
          })}
        />
        <StatCard
          locale={locale}
          label={t("overview.cacheHitLatency")}
          value={formatDuration(locale, overview.cache_hit_latency_ms.p50)}
          definition={t("definitions.cacheHitLatency")}
        />
      </FigureGroup>

      <FigureGroup title={t("overview.groups.cost")}>
        <StatCard
          locale={locale}
          label={t("overview.tokens")}
          value={formatCount(locale, overview.tokens)}
          definition={t("definitions.tokens")}
        />
        <StatCard
          locale={locale}
          label={t("overview.cost")}
          value={formatMoney(locale, overview.cost_usd)}
          definition={t("definitions.cost")}
          warning={
            unpriced > 0
              ? t("overview.unpriced", { count: unpriced })
              : undefined
          }
        />
      </FigureGroup>

      <FigureGroup title={t("overview.groups.cache")}>
        <StatCard
          locale={locale}
          label={t("overview.cacheHitRate")}
          value={formatRate(locale, overview.cache_hit_rate)}
          definition={t("definitions.cacheHitRate")}
          detail={t("overview.cacheHitDetail", {
            hits: t("overview.hits", { count: overview.cache_hits }),
            requests: t("overview.cachedRequests", {
              count: overview.cache_requests,
            }),
          })}
        />
        <StatCard
          locale={locale}
          label={t("overview.savedTokens")}
          value={formatCount(locale, overview.saved_tokens)}
          definition={t("definitions.savedTokens")}
        />
        <StatCard
          locale={locale}
          label={t("overview.savedCost")}
          value={formatMoney(locale, overview.saved_cost_usd)}
          definition={t("definitions.savedCost")}
        />
      </FigureGroup>
    </div>
  );
}

import type { Overview } from "@/api/client";
import { DEFINITIONS } from "@/lib/definitions";
import {
  formatCount,
  formatDuration,
  formatMoney,
  formatRate,
} from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";

import { StatCard } from "./stat-card";

function plural(locale: Locale, count: number, word: string): string {
  return `${formatCount(locale, count)} ${word}${count === 1 ? "" : "s"}`;
}

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
  const {
    latency_ms: latency,
    time_to_first_token_ms: firstToken,
    unpriced_requests: unpriced,
  } = overview;

  return (
    <div className="flex flex-col gap-6">
      <FigureGroup title="Traffic">
        <StatCard
          label="Requests"
          value={formatCount(locale, overview.requests)}
          definition={DEFINITIONS.requests}
          detail={`${formatCount(locale, overview.answered)} answered`}
        />
        <StatCard
          label="Error rate"
          value={formatRate(locale, overview.error_rate)}
          definition={DEFINITIONS.errorRate}
          detail={`${formatCount(locale, overview.failed)} failed. Not counted: ${plural(locale, overview.client_error, "client error")}, ${formatCount(locale, overview.cancelled)} cancelled.`}
        />
        <StatCard
          label="Fallback rate"
          value={formatRate(locale, overview.fallback_rate)}
          definition={DEFINITIONS.fallbackRate}
        />
      </FigureGroup>

      <FigureGroup title="Speed">
        <StatCard
          label="Latency p50"
          value={formatDuration(locale, latency.p50)}
          definition={DEFINITIONS.latency}
          detail={`p95: ${formatDuration(locale, latency.p95)}`}
        />
        <StatCard
          label="Time to first token p50"
          value={formatDuration(locale, firstToken.p50)}
          definition={DEFINITIONS.timeToFirstToken}
          detail={`p95: ${formatDuration(locale, firstToken.p95)} · streams only`}
        />
        <StatCard
          label="Cache hit latency p50"
          value={formatDuration(locale, overview.cache_hit_latency_ms.p50)}
          definition={DEFINITIONS.cacheHitLatency}
        />
      </FigureGroup>

      <FigureGroup title="Tokens and cost">
        <StatCard
          label="Tokens"
          value={formatCount(locale, overview.tokens)}
          definition={DEFINITIONS.tokens}
        />
        <StatCard
          label="Cost"
          value={formatMoney(locale, overview.cost_usd)}
          definition={DEFINITIONS.cost}
          warning={
            unpriced > 0
              ? `${plural(locale, unpriced, "request")} without a price, not included`
              : undefined
          }
        />
      </FigureGroup>

      <FigureGroup title="Cache">
        <StatCard
          label="Cache hit rate"
          value={formatRate(locale, overview.cache_hit_rate)}
          definition={DEFINITIONS.cacheHitRate}
          detail={`${plural(locale, overview.cache_hits, "hit")} of ${plural(locale, overview.cache_requests, "cached request")}`}
        />
        <StatCard
          label="Saved tokens"
          value={formatCount(locale, overview.saved_tokens)}
          definition={DEFINITIONS.savedTokens}
        />
        <StatCard
          label="Saved cost"
          value={formatMoney(locale, overview.saved_cost_usd)}
          definition={DEFINITIONS.savedCost}
        />
      </FigureGroup>
    </div>
  );
}

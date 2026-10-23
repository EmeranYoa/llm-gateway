import type { TargetReport } from "@/api/client";
import { Badge, type BadgeTone } from "@/components/badge";
import { LocalDateTime } from "@/components/local-time";
import { DEFINITIONS } from "@/lib/definitions";
import {
  formatCount,
  formatDuration,
  formatQuota,
  formatRate,
  noValue,
} from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { type Period, PERIOD_LABELS } from "@/lib/period";
import {
  TARGET_HEALTH_DEFINITIONS,
  TARGET_HEALTH_LABELS,
  type TargetHealth,
  targetHealth,
} from "@/lib/target-health";

type Statistics = TargetReport["statistics"];
type LiveState = NonNullable<TargetReport["live"]>;
type Quota = LiveState["rpm"];

export const HEALTH_TONES: Record<TargetHealth, BadgeTone> = {
  healthy: "green",
  cooling_down: "amber",
  breaker_open: "red",
  half_open: "amber",
  quota_full: "orange",
  live_unknown: "slate",
  removed: "slate",
};

/** The status badges of a target: why it gets traffic, or why traffic goes elsewhere. */
export function TargetHealthBadges({ target }: { target: TargetReport }) {
  return (
    <ul aria-label="Status" className="flex flex-wrap gap-1.5">
      {targetHealth(target).map((health) => (
        <li key={health}>
          <Badge
            tone={HEALTH_TONES[health]}
            title={TARGET_HEALTH_DEFINITIONS[health]}
          >
            {TARGET_HEALTH_LABELS[health]}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

/** One figure of a card: a label and its value, in a `<dl>`. */
function Figure({
  label,
  value,
  title,
  highlight = false,
}: {
  label: string;
  value: React.ReactNode;
  title?: string;
  /** Draws the eye to a count that is not zero. */
  highlight?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <dt className="text-slate-600" title={title}>
        {label}
      </dt>
      <dd
        className={`text-right tabular-nums ${highlight ? "font-semibold text-slate-900" : "text-slate-700"}`}
      >
        {value}
      </dd>
    </div>
  );
}

function Count({
  label,
  count,
  locale,
}: {
  label: string;
  count: number;
  locale: Locale;
}) {
  return (
    <Figure
      label={label}
      value={formatCount(locale, count)}
      highlight={count > 0}
    />
  );
}

function SubHeading({ title, children }: { title?: string; children: string }) {
  return (
    <h4
      title={title}
      className="mt-3 text-xs font-semibold tracking-wide text-slate-500 uppercase"
    >
      {children}
    </h4>
  );
}

function PeriodStatistics({
  statistics: s,
  period,
  locale,
}: {
  statistics: Statistics;
  period: Period;
  locale: Locale;
}) {
  return (
    <section aria-label="Statistics of the period">
      <h3 className="text-sm font-semibold text-slate-700">
        {PERIOD_LABELS[period]}
      </h3>
      <dl className="text-sm">
        <Figure
          label="Calls"
          value={formatCount(locale, s.calls)}
          title={DEFINITIONS.targetCalls}
        />
        <Figure
          label="Success rate"
          value={
            s.success_rate === null
              ? noValue(locale)
              : formatRate(locale, s.success_rate)
          }
          title={DEFINITIONS.targetSuccessRate}
        />
        <Figure
          label="Latency p50 / p95"
          value={`${formatDuration(locale, s.latency_p50_ms)} / ${formatDuration(locale, s.latency_p95_ms)}`}
          title={DEFINITIONS.targetLatency}
        />
      </dl>
      <SubHeading title={DEFINITIONS.targetFailures}>Failures</SubHeading>
      <dl className="text-sm">
        <Count
          locale={locale}
          label="Rate limited (429)"
          count={s.rate_limited}
        />
        <Count locale={locale} label="Timeouts" count={s.timeout} />
        <Count locale={locale} label="Unavailable" count={s.unavailable} />
        <Count locale={locale} label="Misconfigured" count={s.misconfigured} />
        <Count
          locale={locale}
          label="Interrupted streams"
          count={s.interrupted}
        />
        <Count
          locale={locale}
          label="Cancelled by the client"
          count={s.cancelled}
        />
      </dl>
      <SubHeading title={DEFINITIONS.targetSkips}>Skipped</SubHeading>
      <dl className="text-sm">
        <Count locale={locale} label="Cooldown" count={s.skipped_cooldown} />
        <Count locale={locale} label="Breaker open" count={s.skipped_breaker} />
        <Count locale={locale} label="Quota full" count={s.skipped_quota} />
      </dl>
      <SubHeading title={DEFINITIONS.targetRequestErrors}>
        Caused by the request
      </SubHeading>
      <dl className="text-sm">
        <Count
          locale={locale}
          label="Invalid requests"
          count={s.invalid_request}
        />
        <Count
          locale={locale}
          label="Too large for the target"
          count={s.context_too_large}
        />
      </dl>
    </section>
  );
}

/** How much of a quota is used, as text and as a bar (the bar is decoration only). */
function QuotaValue({ quota, locale }: { quota: Quota; locale: Locale }) {
  const share =
    quota.limit && quota.used !== null
      ? Math.min(1, quota.used / quota.limit)
      : null;
  return (
    <span className="inline-flex items-center gap-2">
      {share !== null && (
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-16 overflow-hidden rounded bg-slate-200"
        >
          <span
            className={`block h-full ${share >= 1 ? "bg-orange-500" : "bg-sky-600"}`}
            style={{ width: `${share * 100}%` }}
          />
        </span>
      )}
      {formatQuota(locale, quota.used, quota.limit)}
    </span>
  );
}

function CooldownValue({ cooldown }: { cooldown: LiveState["cooldown"] }) {
  if (!cooldown?.active) {
    return "None";
  }
  if (cooldown.until === null) {
    return "Active";
  }
  return (
    <>
      Active until <LocalDateTime iso={cooldown.until} seconds />
    </>
  );
}

function BreakerValue({
  breaker,
  locale,
}: {
  breaker: LiveState["breaker"];
  locale: Locale;
}) {
  if (breaker === null) {
    return noValue(locale);
  }
  if (breaker.state === "open") {
    return breaker.open_until === null ? (
      "Open"
    ) : (
      <>
        Open until <LocalDateTime iso={breaker.open_until} seconds />
      </>
    );
  }
  if (breaker.state === "half_open") {
    return breaker.trial_running
      ? "Half-open, trial call running"
      : "Half-open, waiting for a trial call";
  }
  return "Closed";
}

function LiveStateSection({
  live,
  locale,
}: {
  live: LiveState | null;
  locale: Locale;
}) {
  if (live === null) {
    return (
      <section aria-label="Live state">
        <h3 className="text-sm font-semibold text-slate-700">Now</h3>
        <p className="mt-1 text-sm text-slate-600">
          This target is in no route any more: the gateway does not use it.
        </p>
      </section>
    );
  }
  const known = live.status === "known";
  return (
    <section aria-label="Live state">
      <h3 className="text-sm font-semibold text-slate-700">Now</h3>
      {!known && (
        <p className="mt-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
          Live state unavailable (Redis): cooldown, breaker and used quotas
          cannot be read. Only the configured limits are shown.
        </p>
      )}
      <dl className="text-sm">
        {known && (
          <>
            <Figure
              label="Cooldown"
              value={<CooldownValue cooldown={live.cooldown} />}
              title={DEFINITIONS.cooldown}
              highlight={live.cooldown?.active}
            />
            <Figure
              label="Circuit breaker"
              value={<BreakerValue breaker={live.breaker} locale={locale} />}
              title={DEFINITIONS.breaker}
              highlight={live.breaker?.state !== "closed"}
            />
          </>
        )}
        <Figure
          label="Requests per minute"
          value={<QuotaValue locale={locale} quota={live.rpm} />}
          title={DEFINITIONS.rpm}
        />
        <Figure
          label="Tokens per minute"
          value={<QuotaValue locale={locale} quota={live.tpm} />}
          title={DEFINITIONS.tpm}
        />
        <Figure
          label="Requests per day"
          value={<QuotaValue locale={locale} quota={live.rpd} />}
          title={DEFINITIONS.rpd}
        />
        <Figure
          label="Daily reset"
          value={<LocalDateTime iso={live.rpd.resets_at} />}
        />
      </dl>
    </section>
  );
}

/** One provider/model: its status now, its statistics for the period, and its live state. */
export function TargetCard({
  target,
  period,
  locale,
}: {
  target: TargetReport;
  period: Period;
  locale: Locale;
}) {
  const name = `${target.provider}/${target.model}`;
  return (
    <article
      aria-label={name}
      className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="font-mono text-sm font-semibold break-all text-slate-900">
          <span className="text-slate-500">{target.provider}/</span>
          {target.model}
        </h2>
        <TargetHealthBadges target={target} />
      </header>
      <div className="mt-3 grid gap-6 md:grid-cols-2">
        <PeriodStatistics
          statistics={target.statistics}
          period={period}
          locale={locale}
        />
        <LiveStateSection live={target.live} locale={locale} />
      </div>
    </article>
  );
}

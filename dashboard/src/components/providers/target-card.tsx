import type { TargetReport } from "@/api/client";
import { Badge, type BadgeTone } from "@/components/badge";
import { LocalDateTime } from "@/components/local-time";
import {
  formatCount,
  formatDuration,
  formatQuota,
  formatRate,
  noValue,
} from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { richText } from "@/lib/i18n/rich-text";
import { getTranslator, type Translator } from "@/lib/i18n/translator";
import type { Period } from "@/lib/period";
import { type TargetHealth, targetHealth } from "@/lib/target-health";

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
export function TargetHealthBadges({
  target,
  locale,
}: {
  target: TargetReport;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  return (
    <ul aria-label={t("providers.status")} className="flex flex-wrap gap-1.5">
      {targetHealth(target).map((health) => (
        <li key={health}>
          <Badge
            tone={HEALTH_TONES[health]}
            title={t(`targetHealth.definitions.${health}`)}
          >
            {t(`targetHealth.labels.${health}`)}
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
  const t = getTranslator(locale);
  return (
    <section aria-label={t("providers.statistics")}>
      <h3 className="text-sm font-semibold text-slate-700">
        {t(`period.${period}`)}
      </h3>
      <dl className="text-sm">
        <Figure
          label={t("providers.calls")}
          value={formatCount(locale, s.calls)}
          title={t("definitions.targetCalls")}
        />
        <Figure
          label={t("providers.successRate")}
          value={
            s.success_rate === null
              ? noValue(locale)
              : formatRate(locale, s.success_rate)
          }
          title={t("definitions.targetSuccessRate")}
        />
        <Figure
          label={t("providers.latency")}
          value={`${formatDuration(locale, s.latency_p50_ms)} / ${formatDuration(locale, s.latency_p95_ms)}`}
          title={t("definitions.targetLatency")}
        />
      </dl>
      <SubHeading title={t("definitions.targetFailures")}>
        {t("providers.failures")}
      </SubHeading>
      <dl className="text-sm">
        <Count
          locale={locale}
          label={t("providers.rateLimited")}
          count={s.rate_limited}
        />
        <Count
          locale={locale}
          label={t("providers.timeouts")}
          count={s.timeout}
        />
        <Count
          locale={locale}
          label={t("providers.unavailable")}
          count={s.unavailable}
        />
        <Count
          locale={locale}
          label={t("providers.misconfigured")}
          count={s.misconfigured}
        />
        <Count
          locale={locale}
          label={t("providers.interrupted")}
          count={s.interrupted}
        />
        <Count
          locale={locale}
          label={t("providers.cancelled")}
          count={s.cancelled}
        />
      </dl>
      <SubHeading title={t("definitions.targetSkips")}>
        {t("providers.skipped")}
      </SubHeading>
      <dl className="text-sm">
        <Count
          locale={locale}
          label={t("providers.cooldown")}
          count={s.skipped_cooldown}
        />
        <Count
          locale={locale}
          label={t("providers.breakerOpen")}
          count={s.skipped_breaker}
        />
        <Count
          locale={locale}
          label={t("providers.quotaFull")}
          count={s.skipped_quota}
        />
      </dl>
      <SubHeading title={t("definitions.targetRequestErrors")}>
        {t("providers.causedByRequest")}
      </SubHeading>
      <dl className="text-sm">
        <Count
          locale={locale}
          label={t("providers.invalidRequests")}
          count={s.invalid_request}
        />
        <Count
          locale={locale}
          label={t("providers.tooLarge")}
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

function CooldownValue({
  cooldown,
  t,
}: {
  cooldown: LiveState["cooldown"];
  t: Translator;
}) {
  if (!cooldown?.active) {
    return t("providers.cooldownNone");
  }
  if (cooldown.until === null) {
    return t("providers.cooldownActive");
  }
  return richText(t, "providers.cooldownUntil", {
    time: <LocalDateTime iso={cooldown.until} seconds />,
  });
}

function BreakerValue({
  breaker,
  locale,
}: {
  breaker: LiveState["breaker"];
  locale: Locale;
}) {
  const t = getTranslator(locale);
  if (breaker === null) {
    return noValue(locale);
  }
  if (breaker.state === "open") {
    return breaker.open_until === null
      ? t("providers.breakerOpenState")
      : richText(t, "providers.breakerOpenUntil", {
          time: <LocalDateTime iso={breaker.open_until} seconds />,
        });
  }
  if (breaker.state === "half_open") {
    return breaker.trial_running
      ? t("providers.halfOpenTrialRunning")
      : t("providers.halfOpenWaiting");
  }
  return t("providers.breakerClosed");
}

function LiveStateSection({
  live,
  locale,
}: {
  live: LiveState | null;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  if (live === null) {
    return (
      <section aria-label={t("providers.liveState")}>
        <h3 className="text-sm font-semibold text-slate-700">
          {t("providers.now")}
        </h3>
        <p className="mt-1 text-sm text-slate-600">{t("providers.removed")}</p>
      </section>
    );
  }
  const known = live.status === "known";
  return (
    <section aria-label={t("providers.liveState")}>
      <h3 className="text-sm font-semibold text-slate-700">
        {t("providers.now")}
      </h3>
      {!known && (
        <p className="mt-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
          {t("providers.liveUnknown")}
        </p>
      )}
      <dl className="text-sm">
        {known && (
          <>
            <Figure
              label={t("providers.cooldown")}
              value={<CooldownValue cooldown={live.cooldown} t={t} />}
              title={t("definitions.cooldown")}
              highlight={live.cooldown?.active}
            />
            <Figure
              label={t("providers.breaker")}
              value={<BreakerValue breaker={live.breaker} locale={locale} />}
              title={t("definitions.breaker")}
              highlight={live.breaker?.state !== "closed"}
            />
          </>
        )}
        <Figure
          label={t("providers.rpm")}
          value={<QuotaValue locale={locale} quota={live.rpm} />}
          title={t("definitions.rpm")}
        />
        <Figure
          label={t("providers.tpm")}
          value={<QuotaValue locale={locale} quota={live.tpm} />}
          title={t("definitions.tpm")}
        />
        <Figure
          label={t("providers.rpd")}
          value={<QuotaValue locale={locale} quota={live.rpd} />}
          title={t("definitions.rpd")}
        />
        <Figure
          label={t("providers.dailyReset")}
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
        <TargetHealthBadges target={target} locale={locale} />
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

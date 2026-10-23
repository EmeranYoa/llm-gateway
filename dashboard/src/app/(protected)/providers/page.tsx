import {
  AdminApiError,
  getTargets,
  keepApiError,
  type TargetsReport,
} from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { AutoRefresh } from "@/components/auto-refresh";
import { PeriodFilter } from "@/components/filters";
import { TimeZoneName } from "@/components/local-time";
import { HEALTH_TONES, TargetCard } from "@/components/providers/target-card";
import { Badge } from "@/components/badge";
import { getI18n } from "@/lib/i18n/server";
import type { Locale } from "@/lib/i18n/locale";
import { richText } from "@/lib/i18n/rich-text";
import { getTranslator } from "@/lib/i18n/translator";
import { type Period, parsePeriod } from "@/lib/period";
import { type TargetHealth, targetHealth } from "@/lib/target-health";

/**
 * Providers & models: one card per target (provider/model), with its
 * statistics for the period and its live state, to see at a glance which one
 * struggles and why traffic moves elsewhere. The period lives in the URL:
 * `/providers?period=7d`.
 */
export default async function ProvidersPage({
  searchParams,
}: PageProps<"/providers">) {
  const period = parsePeriod((await searchParams).period);

  const { locale, t } = await getI18n();
  const loaded = await loadTargets(period).catch(keepApiError);
  const report = loaded instanceof AdminApiError ? null : loaded;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("providers.title")}</h1>
        <PeriodFilter value={period} />
      </div>
      <AutoRefresh
        updatedAt={report?.loadedAt ?? null}
        failed={report === null}
        dataKey={period}
      >
        {report ? (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-slate-600">
              <TimeZoneName />
            </p>
            <TargetsList
              targets={report.targets.targets}
              period={period}
              locale={locale}
            />
          </div>
        ) : (
          loaded instanceof AdminApiError && (
            <ApiErrorNotice error={loaded} locale={locale} />
          )
        )}
      </AutoRefresh>
    </section>
  );
}

/**
 * The report and when it was loaded. The report has no date of its own, and its
 * live state is read when it is answered, so the load time is its age.
 */
async function loadTargets(
  period: Period,
): Promise<{ targets: TargetsReport; loadedAt: string }> {
  const targets = await getTargets(period);
  return { targets, loadedAt: new Date().toISOString() };
}

function TargetsList({
  targets,
  period,
  locale,
}: {
  targets: TargetsReport["targets"];
  period: Period;
  locale: Locale;
}) {
  if (targets.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        {richText(getTranslator(locale), "providers.empty", {
          file: <code className="font-mono text-xs">config/gateway.yaml</code>,
        })}
      </p>
    );
  }
  return (
    <>
      <HealthSummary targets={targets} locale={locale} />
      <div className="flex flex-col gap-4">
        {targets.map((target) => (
          <TargetCard
            key={`${target.provider}/${target.model}`}
            target={target}
            period={period}
            locale={locale}
          />
        ))}
      </div>
    </>
  );
}

/** How many targets are in each state, by their most blocking reason. */
function HealthSummary({
  targets,
  locale,
}: {
  targets: TargetsReport["targets"];
  locale: Locale;
}) {
  const t = getTranslator(locale);
  const counts = new Map<TargetHealth, number>();
  for (const target of targets) {
    const main = targetHealth(target)[0];
    counts.set(main, (counts.get(main) ?? 0) + 1);
  }
  return (
    <ul
      aria-label={t("providers.byStatus")}
      className="flex flex-wrap items-center gap-2 text-sm"
    >
      {[...counts].map(([health, count]) => (
        <li key={health}>
          <Badge tone={HEALTH_TONES[health]}>
            {t("providers.statusCount", {
              status: t(`targetHealth.labels.${health}`),
              count,
            })}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

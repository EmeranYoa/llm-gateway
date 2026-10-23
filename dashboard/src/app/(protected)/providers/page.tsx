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
import { formatCount } from "@/lib/format";
import { type Period, parsePeriod } from "@/lib/period";
import {
  TARGET_HEALTH_LABELS,
  type TargetHealth,
  targetHealth,
} from "@/lib/target-health";

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

  const loaded = await loadTargets(period).catch(keepApiError);
  const report = loaded instanceof AdminApiError ? null : loaded;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">Providers & models</h1>
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
            <TargetsList targets={report.targets.targets} period={period} />
          </div>
        ) : (
          loaded instanceof AdminApiError && <ApiErrorNotice error={loaded} />
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
}: {
  targets: TargetsReport["targets"];
  period: Period;
}) {
  if (targets.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        No target is configured: add routes to{" "}
        <code className="font-mono text-xs">config/gateway.yaml</code>.
      </p>
    );
  }
  return (
    <>
      <HealthSummary targets={targets} />
      <div className="flex flex-col gap-4">
        {targets.map((target) => (
          <TargetCard
            key={`${target.provider}/${target.model}`}
            target={target}
            period={period}
          />
        ))}
      </div>
    </>
  );
}

/** How many targets are in each state, by their most blocking reason. */
function HealthSummary({ targets }: { targets: TargetsReport["targets"] }) {
  const counts = new Map<TargetHealth, number>();
  for (const target of targets) {
    const main = targetHealth(target)[0];
    counts.set(main, (counts.get(main) ?? 0) + 1);
  }
  return (
    <ul
      aria-label="Targets by status"
      className="flex flex-wrap items-center gap-2 text-sm"
    >
      {[...counts].map(([health, count]) => (
        <li key={health}>
          <Badge tone={HEALTH_TONES[health]}>
            {TARGET_HEALTH_LABELS[health]}: {formatCount(count)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

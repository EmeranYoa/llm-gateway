import {
  AdminApiError,
  getOverview,
  listTenantNames,
  keepApiError,
} from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { AutoRefresh } from "@/components/auto-refresh";
import { PeriodFilter, TenantFilter } from "@/components/filters";
import { PeriodRange } from "@/components/local-time";
import { OverviewCharts } from "@/components/overview-charts";
import { OverviewFigures } from "@/components/overview-figures";
import { parsePeriod, parseTenant } from "@/lib/period";

/**
 * Health, cost and cache savings of the gateway for a period, for every tenant
 * or for one. Filters live in the URL: `/?period=7d&tenant=acme`.
 */
export default async function OverviewPage({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  const period = parsePeriod(params.period);
  const tenant = parseTenant(params.tenant);

  const [report, tenantNames] = await Promise.all([
    getOverview(period, tenant).catch(keepApiError),
    loadTenantNames(),
  ]);
  const overview = report instanceof AdminApiError ? null : report;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">
          Overview{tenant !== null && `: ${tenant}`}
        </h1>
        <div className="flex flex-wrap gap-4">
          <PeriodFilter value={period} />
          <TenantFilter value={tenant} tenants={tenantNames} />
        </div>
      </div>
      <AutoRefresh
        updatedAt={overview?.end ?? null}
        failed={overview === null}
        dataKey={`${period}|${tenant ?? ""}`}
      >
        {overview ? (
          <div className="flex flex-col gap-6">
            <PeriodRange start={overview.start} end={overview.end} />
            <OverviewFigures overview={overview} />
            <OverviewCharts series={overview.series} period={period} />
          </div>
        ) : (
          report instanceof AdminApiError && <ApiErrorNotice error={report} />
        )}
      </AutoRefresh>
    </section>
  );
}

/**
 * Names of the tenants, for the tenant filter. Without them the filter still
 * works with the selected tenant, so an error here does not hide the overview.
 */
async function loadTenantNames(): Promise<string[]> {
  const names = await listTenantNames().catch(keepApiError);
  return names instanceof AdminApiError ? [] : names;
}

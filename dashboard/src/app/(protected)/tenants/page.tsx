import { AdminApiError, getTenantStatistics, keepApiError } from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { AutoRefresh } from "@/components/auto-refresh";
import { PeriodFilter } from "@/components/filters";
import { PeriodRange } from "@/components/local-time";
import { TenantsTable } from "@/components/tenants-table";
import { getI18n } from "@/lib/i18n/server";
import { parsePeriod } from "@/lib/period";

/**
 * What each tenant did in the period. A row opens the overview of the tenant.
 * The period lives in the URL: `/tenants?period=7d`.
 */
export default async function TenantsPage({
  searchParams,
}: PageProps<"/tenants">) {
  const period = parsePeriod((await searchParams).period);

  const { locale, t } = await getI18n();
  const report = await getTenantStatistics(period).catch(keepApiError);
  const list = report instanceof AdminApiError ? null : report;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("tenants.title")}</h1>
        <PeriodFilter value={period} />
      </div>
      <AutoRefresh
        updatedAt={list?.end ?? null}
        failed={list === null}
        dataKey={period}
      >
        {list ? (
          <div className="flex flex-col gap-3">
            <PeriodRange start={list.start} end={list.end} />
            <TenantsTable
              tenants={list.tenants}
              period={period}
              locale={locale}
            />
          </div>
        ) : (
          report instanceof AdminApiError && (
            <ApiErrorNotice error={report} locale={locale} />
          )
        )}
      </AutoRefresh>
    </section>
  );
}

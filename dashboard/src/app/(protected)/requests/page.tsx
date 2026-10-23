import {
  AdminApiError,
  keepApiError,
  listRequests,
  type RequestPage,
} from "@/api/client";
import { listTenantNames } from "@/api/tenant-keys";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { AutoRefresh } from "@/components/auto-refresh";
import {
  AliasFilter,
  PeriodFilter,
  RequestStatusFilter,
  TenantFilter,
} from "@/components/filters";
import { TimeZoneName } from "@/components/local-time";
import { RequestsPagination } from "@/components/requests/pagination";
import { RequestsTable } from "@/components/requests/requests-table";
import {
  parseRequestFilters,
  type RequestFilters,
  requestListQuery,
} from "@/lib/request-filters";

/**
 * The requests of a period, newest first, 50 per page, to find one and open
 * its routing path. Filters and page live in the URL:
 * `/requests?period=7d&tenant=acme&alias=chat-fast&status=failed&cursor=...`.
 *
 * The first page reloads every 10 s. Older pages do not: new requests would
 * not show there, and the operator is reading them.
 */
export default async function RequestsPage({
  searchParams,
}: PageProps<"/requests">) {
  const { filters, cursor } = parseRequestFilters(await searchParams);

  const [loaded, tenantNames] = await Promise.all([
    loadPage(filters, cursor).catch(keepApiError),
    loadTenantNames(),
  ]);
  const result = loaded instanceof AdminApiError ? null : loaded;

  const content = result ? (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-600">
        <TimeZoneName />
      </p>
      <RequestsTable
        requests={result.page.items}
        filters={filters}
        cursor={cursor}
      />
      <RequestsPagination
        filters={filters}
        cursor={cursor}
        nextCursor={result.page.next_cursor}
      />
    </div>
  ) : (
    loaded instanceof AdminApiError && <ApiErrorNotice error={loaded} />
  );

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">Requests</h1>
        <div className="flex flex-wrap gap-4">
          <PeriodFilter value={filters.period} />
          <TenantFilter value={filters.tenant} tenants={tenantNames} />
          <AliasFilter
            value={filters.alias}
            suggestions={result?.page.items.map((item) => item.alias) ?? []}
          />
          <RequestStatusFilter value={filters.status} />
        </div>
      </div>
      {cursor === null ? (
        <AutoRefresh
          updatedAt={result?.loadedAt ?? null}
          failed={result === null}
          dataKey={requestListQuery(filters)}
        >
          {content}
        </AutoRefresh>
      ) : (
        <>
          <p className="text-xs text-slate-600">
            Older requests: auto-refresh is off on this page.
          </p>
          {content}
        </>
      )}
    </section>
  );
}

/** One page of requests and when it was loaded (the page has no date of its own). */
async function loadPage(
  filters: RequestFilters,
  cursor: string | null,
): Promise<{ page: RequestPage; loadedAt: string }> {
  const page = await listRequests(filters, cursor);
  return { page, loadedAt: new Date().toISOString() };
}

/**
 * Names of the tenants, for the tenant filter. Without them the filter still
 * works with the selected tenant, so an error here does not hide the requests.
 */
async function loadTenantNames(): Promise<string[]> {
  const names = await listTenantNames().catch(keepApiError);
  return names instanceof AdminApiError ? [] : names;
}

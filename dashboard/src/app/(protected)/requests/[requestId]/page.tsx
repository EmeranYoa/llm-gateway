import Link from "next/link";

import {
  AdminApiError,
  getRequest,
  keepApiError,
  type RequestDetail,
} from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { LocalDateTime, TimeZoneName } from "@/components/local-time";
import {
  AnsweredBy,
  cacheLabel,
  RequestStatusBadge,
} from "@/components/requests/request-status-badge";
import { RoutingPath } from "@/components/requests/routing-path";
import {
  formatCount,
  formatDuration,
  formatMoney,
  NO_VALUE,
} from "@/lib/format";
import { parseRequestFilters, requestsHref } from "@/lib/request-filters";

/**
 * One request: its summary and its routing path, to debug it. The search params
 * are those of the list it was opened from, so the back link returns there.
 * It does not refresh by itself: a request does not change once logged.
 */
export default async function RequestDetailPage({
  params,
  searchParams,
}: PageProps<"/requests/[requestId]">) {
  const { requestId } = await params;
  const { filters, cursor } = parseRequestFilters(await searchParams);

  const detail = await getRequest(requestId).catch(keepApiError);

  return (
    <section className="flex flex-col gap-4">
      <Link
        href={requestsHref(filters, cursor)}
        className="self-start text-sm text-sky-800 hover:underline"
      >
        ← Back to the requests
      </Link>
      <h1 className="text-xl font-semibold">
        Request{" "}
        <span className="font-mono text-base break-all">{requestId}</span>
      </h1>
      {detail instanceof AdminApiError ? (
        detail.status === 404 ? (
          <div
            role="alert"
            className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          >
            <p className="font-medium">No request with this id.</p>
            <p>
              Check the id. Old requests may have been removed from the usage
              log by its retention.
            </p>
          </div>
        ) : (
          <ApiErrorNotice error={detail} />
        )
      ) : (
        <>
          <RequestOverview request={detail} />
          <section
            aria-labelledby="path-heading"
            className="flex flex-col gap-3"
          >
            <h2 id="path-heading" className="text-lg font-semibold">
              Routing path
            </h2>
            <p className="text-sm text-slate-600">
              Every target the gateway examined for this request, in order.
            </p>
            <RoutingPath steps={detail.routing_path} />
          </section>
        </>
      )}
    </section>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}

/** The summary of a request: when, who, which alias, and how it ended. */
function RequestOverview({ request }: { request: RequestDetail }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <dl
        aria-label="Summary"
        className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-4"
      >
        <Item
          label="Received"
          value={<LocalDateTime iso={request.created_at} seconds />}
        />
        <Item label="Tenant" value={request.tenant ?? NO_VALUE} />
        <Item
          label="Alias"
          value={<span className="font-mono text-xs">{request.alias}</span>}
        />
        <Item
          label="Status"
          value={<RequestStatusBadge status={request.status} />}
        />
        <Item label="HTTP status" value={request.status_code ?? NO_VALUE} />
        <Item
          label="Answered by"
          value={
            <AnsweredBy provider={request.provider} model={request.model} />
          }
        />
        <Item label="Attempts" value={formatCount(request.attempts)} />
        <Item label="Stream" value={request.stream ? "yes" : "no"} />
        <Item label="Latency" value={formatDuration(request.latency_ms)} />
        <Item label="Cost" value={formatMoney(request.cost_usd)} />
        <Item label="Cache" value={cacheLabel(request.cache)} />
      </dl>
      <p className="mt-3 text-xs text-slate-600">
        <TimeZoneName />
      </p>
    </div>
  );
}

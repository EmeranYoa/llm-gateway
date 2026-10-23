import Link from "next/link";

import type { RequestSummary } from "@/api/client";
import { LocalDateTime } from "@/components/local-time";
import {
  formatCount,
  formatDuration,
  formatMoney,
  noValue,
} from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { type RequestFilters, requestHref } from "@/lib/request-filters";

import {
  AnsweredBy,
  cacheLabel,
  RequestStatusBadge,
} from "./request-status-badge";

type RequestsTableProps = {
  requests: RequestSummary[];
  /** Filters and page of the list, carried to the detail so its back link returns here. */
  filters: RequestFilters;
  cursor: string | null;
  locale: Locale;
};

const HEADERS: { label: string; title?: string; numeric?: boolean }[] = [
  { label: "Time" },
  { label: "Tenant" },
  { label: "Alias" },
  {
    label: "Status",
    title:
      "Answered, failed (gateway or providers), client error (request refused) or cancelled (the client left).",
  },
  {
    label: "HTTP",
    title: "HTTP status of the last target examined.",
    numeric: true,
  },
  { label: "Answered by", title: "Provider and model of the answer." },
  {
    label: "Attempts",
    title: "Targets examined, skips included.",
    numeric: true,
  },
  { label: "Stream" },
  {
    label: "Latency",
    title: "Sum of the durations of the attempts.",
    numeric: true,
  },
  { label: "Cost", numeric: true },
  {
    label: "Cache",
    title:
      "What the response cache did: hit, miss, bypass or unavailable. Off when the alias does not use it.",
  },
];

/** One row per request, newest first. The time of a row opens its detail. */
export function RequestsTable({
  requests,
  filters,
  cursor,
  locale,
}: RequestsTableProps) {
  if (requests.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        No request matches these filters in the period.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-600">
          <tr>
            {HEADERS.map((header) => (
              <th
                key={header.label}
                scope="col"
                title={header.title}
                className={`px-3 py-2 font-medium whitespace-nowrap ${header.numeric ? "text-right" : ""}`}
              >
                {header.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {requests.map((request) => (
            <tr
              key={request.request_id}
              className="relative focus-within:bg-sky-50 hover:bg-slate-50"
            >
              <th
                scope="row"
                className="px-3 py-2 text-left font-normal whitespace-nowrap"
              >
                <Link
                  href={requestHref(request.request_id, filters, cursor)}
                  aria-label={`Details of request ${request.request_id}`}
                  title={request.request_id}
                  className="text-sky-800 after:absolute after:inset-0 hover:underline focus:outline-none"
                >
                  <LocalDateTime iso={request.created_at} seconds />
                </Link>
              </th>
              <td className="px-3 py-2">
                {request.tenant ?? (
                  <span className="text-slate-500">{noValue(locale)}</span>
                )}
              </td>
              <td className="px-3 py-2 font-mono text-xs">{request.alias}</td>
              <td className="px-3 py-2">
                <RequestStatusBadge status={request.status} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {request.status_code ?? noValue(locale)}
              </td>
              <td className="px-3 py-2">
                <AnsweredBy provider={request.provider} model={request.model} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {formatCount(locale, request.attempts)}
              </td>
              <td className="px-3 py-2">{request.stream ? "yes" : "no"}</td>
              <td className="px-3 py-2 text-right whitespace-nowrap tabular-nums">
                {formatDuration(locale, request.latency_ms)}
              </td>
              <td className="px-3 py-2 text-right whitespace-nowrap tabular-nums">
                {formatMoney(locale, request.cost_usd)}
              </td>
              <td className="px-3 py-2">{cacheLabel(request.cache)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

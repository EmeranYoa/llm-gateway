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
import { getTranslator } from "@/lib/i18n/translator";
import { type RequestFilters, requestHref } from "@/lib/request-filters";
import type { en } from "@/messages/en";

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

type Column = keyof typeof en.requests.columns;
type DefinedColumn = keyof typeof en.requests.columnDefinitions;

/**
 * The columns, in order. Each has a header (`requests.columns`); some have a
 * definition in the `title` of the header (`requests.columnDefinitions`).
 */
const COLUMNS: {
  id: Column;
  definition?: DefinedColumn;
  numeric?: boolean;
}[] = [
  { id: "time" },
  { id: "tenant" },
  { id: "alias" },
  { id: "status", definition: "status" },
  { id: "http", definition: "http", numeric: true },
  { id: "answeredBy", definition: "answeredBy" },
  { id: "attempts", definition: "attempts", numeric: true },
  { id: "stream" },
  { id: "latency", definition: "latency", numeric: true },
  { id: "cost", numeric: true },
  { id: "cache", definition: "cache" },
];

/** One row per request, newest first. The time of a row opens its detail. */
export function RequestsTable({
  requests,
  filters,
  cursor,
  locale,
}: RequestsTableProps) {
  const t = getTranslator(locale);
  if (requests.length === 0) {
    return <p className="text-sm text-slate-600">{t("requests.empty")}</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-600">
          <tr>
            {COLUMNS.map((column) => (
              <th
                key={column.id}
                scope="col"
                title={
                  column.definition &&
                  t(`requests.columnDefinitions.${column.definition}`)
                }
                className={`px-3 py-2 font-medium whitespace-nowrap ${column.numeric ? "text-right" : ""}`}
              >
                {t(`requests.columns.${column.id}`)}
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
                  aria-label={t("requests.detailsOf", {
                    id: request.request_id,
                  })}
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
                <RequestStatusBadge status={request.status} locale={locale} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {request.status_code ?? noValue(locale)}
              </td>
              <td className="px-3 py-2">
                <AnsweredBy
                  provider={request.provider}
                  model={request.model}
                  locale={locale}
                />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {formatCount(locale, request.attempts)}
              </td>
              <td className="px-3 py-2">
                {request.stream ? t("requests.yes") : t("requests.no")}
              </td>
              <td className="px-3 py-2 text-right whitespace-nowrap tabular-nums">
                {formatDuration(locale, request.latency_ms)}
              </td>
              <td className="px-3 py-2 text-right whitespace-nowrap tabular-nums">
                {formatMoney(locale, request.cost_usd)}
              </td>
              <td className="px-3 py-2">{cacheLabel(request.cache, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

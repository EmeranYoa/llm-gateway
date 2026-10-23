/**
 * Filters of the Requests screen, kept in the URL:
 * `/requests?period=7d&tenant=acme&alias=chat-fast&status=failed&cursor=...`.
 *
 * The detail page of a request receives the same params, so its "back" link
 * returns to the same page of the list with the same filters.
 */

import type { components } from "@/api/schema";

import { type Period, parsePeriod, parseTenant } from "./period";
import { CURSOR_PARAM } from "./search-params";

/**
 * `answered`, `failed`, `client_error` or `cancelled` (see `app/admin_api/request_status.py`).
 * Labels and definitions: `requestStatus.labels` and `requestStatus.definitions`
 * in the dictionaries.
 */
export type RequestStatus = components["schemas"]["RequestStatus"];

/** The statuses, in the order the screens offer them. */
export const REQUEST_STATUSES: readonly RequestStatus[] = [
  "answered",
  "failed",
  "client_error",
  "cancelled",
];

/** Filters of the request list. `null` means no filter on that field. */
export type RequestFilters = {
  period: Period;
  tenant: string | null;
  alias: string | null;
  status: RequestStatus | null;
};

/** A value of a URL search param, as Next.js gives it to a page. */
type SearchParamValue = string | string[] | undefined;

function firstValue(value: SearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The status of the `status` search param, or null (every status) when missing or unknown. */
export function parseRequestStatus(
  value: SearchParamValue,
): RequestStatus | null {
  const first = firstValue(value);
  return REQUEST_STATUSES.find((status) => status === first) ?? null;
}

/** The filters and the page cursor of the search params of the Requests screen. */
export function parseRequestFilters(params: Record<string, SearchParamValue>): {
  filters: RequestFilters;
  cursor: string | null;
} {
  const alias = firstValue(params.alias)?.trim();
  const cursor = firstValue(params[CURSOR_PARAM]);
  return {
    filters: {
      period: parsePeriod(params.period),
      tenant: parseTenant(params.tenant),
      alias: alias ? alias : null,
      status: parseRequestStatus(params.status),
    },
    cursor: cursor ? cursor : null,
  };
}

/** The query string of a page of the list: `period=7d&tenant=acme&cursor=...`. */
export function requestListQuery(
  filters: RequestFilters,
  cursor: string | null = null,
): string {
  const params = new URLSearchParams({ period: filters.period });
  for (const key of ["tenant", "alias", "status"] as const) {
    const value = filters[key];
    if (value !== null) {
      params.set(key, value);
    }
  }
  if (cursor !== null) {
    params.set(CURSOR_PARAM, cursor);
  }
  return params.toString();
}

/** A page of the request list: the first one, or the one after `cursor`. */
export function requestsHref(
  filters: RequestFilters,
  cursor: string | null = null,
): string {
  return `/requests?${requestListQuery(filters, cursor)}`;
}

/** The detail of a request, carrying the filters and page of the list it was opened from. */
export function requestHref(
  requestId: string,
  filters: RequestFilters,
  cursor: string | null = null,
): string {
  return `/requests/${encodeURIComponent(requestId)}?${requestListQuery(filters, cursor)}`;
}

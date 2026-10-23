import "server-only";

import { redirect } from "next/navigation";

import { readDashboardConfig } from "@/lib/config";
import { type RequestFilters, requestListQuery } from "@/lib/request-filters";
import { getSession } from "@/lib/session";

import type { Period } from "@/lib/period";

import type { components, paths } from "./schema";

/**
 * Client of the admin API, used only by the Next.js server.
 *
 * The admin key lives in the encrypted session cookie. This module reads it on
 * the server and sends it to the admin API: the browser never sees it.
 */

export type Me =
  paths["/admin/v1/me"]["get"]["responses"][200]["content"]["application/json"];

export type Overview = components["schemas"]["Overview"];
export type SeriesPoint = components["schemas"]["SeriesPoint"];
export type TenantStatisticsList =
  components["schemas"]["TenantStatisticsList"];
export type TenantStatistics = components["schemas"]["TenantStatistics"];
export type TargetsReport = components["schemas"]["TargetsReport"];
export type TargetReport = components["schemas"]["TargetReport"];
export type RequestPage = components["schemas"]["RequestPage"];
export type RequestSummary = components["schemas"]["RequestSummary"];
export type RequestDetail = components["schemas"]["RequestDetail"];
export type RoutingStep = components["schemas"]["RoutingStep"];

/** Where to send the operator when the admin API refuses the key of the session. */
export const SESSION_EXPIRED_PATH = "/session-expired";

/** Seconds to wait for the admin API before showing an error. */
const REQUEST_TIMEOUT_MS = 10_000;

/** The admin API failed, or answered with an error other than 401. */
export class AdminApiError extends Error {
  override name = "AdminApiError";

  constructor(
    message: string,
    /** HTTP status of the answer, or null when the admin API could not be reached. */
    readonly status: number | null,
    /** The `code` of the OpenAI-format error body, when there is one. */
    readonly code: string | null,
  ) {
    super(message);
  }
}

/**
 * For `.catch()` on a call of this module: an `AdminApiError` becomes a value
 * the page can show; anything else is thrown again (a redirect to /login, or
 * a bug). Returning the error lets a page show it instead of its data.
 */
export function keepApiError(caught: unknown): AdminApiError {
  if (caught instanceof AdminApiError) {
    return caught;
  }
  throw caught;
}

/** Return the operator who owns the admin key of the session. */
export async function getMe(): Promise<Me> {
  return callWithSession<Me>("/admin/v1/me");
}

/**
 * Totals and time series of a period, for every tenant or for one.
 *
 * An unknown tenant raises an `AdminApiError` with status 404 (`tenant_not_found`).
 */
export async function getOverview(
  period: Period,
  tenant: string | null,
): Promise<Overview> {
  const query = new URLSearchParams({ period });
  if (tenant !== null) {
    query.set("tenant", tenant);
  }
  return callWithSession<Overview>(`/admin/v1/overview?${query}`);
}

/** Names of every tenant, in alphabetical order: for the tenant filters. */
export async function listTenantNames(): Promise<string[]> {
  const list = await callWithSession<components["schemas"]["TenantNames"]>(
    "/admin/v1/tenant-names",
  );
  return list.tenants;
}

/** One row per tenant for the period, most requests first. */
export async function getTenantStatistics(
  period: Period,
): Promise<TenantStatisticsList> {
  const query = new URLSearchParams({ period });
  return callWithSession<TenantStatisticsList>(`/admin/v1/tenants?${query}`);
}

/**
 * Statistics of every target (provider/model) over the period, and its live
 * state in Redis: cooldown, circuit breaker and used quotas.
 */
export async function getTargets(period: Period): Promise<TargetsReport> {
  const query = new URLSearchParams({ period });
  return callWithSession<TargetsReport>(`/admin/v1/targets?${query}`);
}

/**
 * One page of requests (50), newest first. `cursor` is the `next_cursor` of the
 * previous page, or null for the first page.
 *
 * An invalid cursor raises an `AdminApiError` with status 400 (`invalid_cursor`).
 */
export async function listRequests(
  filters: RequestFilters,
  cursor: string | null,
): Promise<RequestPage> {
  // The admin API takes the same params as the URL of the Requests screen.
  const query = requestListQuery(filters, cursor);
  return callWithSession<RequestPage>(`/admin/v1/requests?${query}`);
}

/**
 * One request and its routing path.
 *
 * An unknown id raises an `AdminApiError` with status 404 (`request_not_found`).
 */
export async function getRequest(requestId: string): Promise<RequestDetail> {
  return callWithSession<RequestDetail>(
    `/admin/v1/requests/${encodeURIComponent(requestId)}`,
  );
}

/**
 * Check an admin key typed on the sign-in page, before it goes in the session.
 *
 * Returns the operator, or null when the admin API refuses the key.
 */
export async function checkAdminKey(adminKey: string): Promise<Me | null> {
  const response = await callAdminApi("/admin/v1/me", adminKey);
  if (response.status === 401) {
    return null;
  }
  return readBody<Me>(response);
}

/** A write to the admin API: the HTTP method and the JSON body, if any. */
export type AdminApiWrite = {
  method: "POST" | "PUT";
  body?: unknown;
};

/**
 * Call the admin API with the admin key of the session and return the JSON answer.
 *
 * Without a session, sends to the sign-in page; on a 401, ends the session.
 * Any other error is raised as an `AdminApiError`.
 */
export async function callWithSession<T>(
  path: string,
  write?: AdminApiWrite,
): Promise<T> {
  const { adminKey } = await getSession();
  if (!adminKey) {
    redirect("/login");
  }
  const response = await callAdminApi(path, adminKey, write);
  if (response.status === 401) {
    // The key was revoked, or expired from the admin API's point of view.
    redirect(SESSION_EXPIRED_PATH);
  }
  return readBody<T>(response);
}

async function callAdminApi(
  path: string,
  adminKey: string,
  write?: AdminApiWrite,
): Promise<Response> {
  const { adminApiUrl } = readDashboardConfig();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${adminKey}`,
    Accept: "application/json",
  };
  if (write?.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  try {
    return await fetch(`${adminApiUrl}${path}`, {
      method: write?.method ?? "GET",
      headers,
      body: write?.body === undefined ? undefined : JSON.stringify(write.body),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new AdminApiError(
      "The admin API cannot be reached. Check that it is running.",
      null,
      "admin_api_unreachable",
    );
  }
}

async function readBody<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await toAdminApiError(response);
  }
  return (await response.json()) as T;
}

/** Errors of the admin API are in OpenAI format: {"error": {message, type, param, code}}. */
type ErrorBody = {
  error?: { message?: unknown; code?: unknown };
};

async function toAdminApiError(response: Response): Promise<AdminApiError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // Not JSON: keep the generic message below.
  }
  const message =
    typeof body.error?.message === "string"
      ? body.error.message
      : `The admin API answered with HTTP ${response.status}.`;
  const code = typeof body.error?.code === "string" ? body.error.code : null;
  return new AdminApiError(message, response.status, code);
}

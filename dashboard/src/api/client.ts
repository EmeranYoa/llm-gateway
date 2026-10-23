import "server-only";

import { headers as requestHeaders } from "next/headers";
import { redirect } from "next/navigation";

import { readDashboardConfig } from "@/lib/config";
import { type RequestFilters, requestListQuery } from "@/lib/request-filters";
import { getSession } from "@/lib/session";

import type { Period } from "@/lib/period";

import type { components, paths } from "./schema";

/**
 * Client of the admin API, used only by the Next.js server.
 *
 * The session token of the admin API lives in the encrypted session cookie.
 * This module reads it on the server and sends it to the admin API: the
 * browser never sees it.
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

/** Where to send the operator when the admin API refuses the session token. */
export const SESSION_EXPIRED_PATH = "/session-expired";

/** Where to send the operator who must choose a new password first. */
export const CHANGE_PASSWORD_PATH = "/change-password";

/** The error code of the admin API while the operator must change their password. */
export const PASSWORD_CHANGE_REQUIRED = "password_change_required";

/** Seconds to wait for the admin API before showing an error. */
const REQUEST_TIMEOUT_MS = 10_000;

/** The admin API failed, or answered with an error. */
export class AdminApiError extends Error {
  override name = "AdminApiError";

  constructor(
    message: string,
    /** HTTP status of the answer, or null when the admin API could not be reached. */
    readonly status: number | null,
    /** The `code` of the OpenAI-format error body, when there is one. */
    readonly code: string | null,
    /** Seconds to wait before trying again (`Retry-After`), when the answer says. */
    readonly retryAfterSeconds: number | null = null,
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

/** Return the operator signed in with the session. */
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

/** A write to the admin API: the HTTP method and the JSON body, if any. */
export type AdminApiWrite = {
  method: "POST" | "PUT" | "DELETE";
  body?: unknown;
};

/**
 * Call the admin API with the session token of the cookie and return the JSON
 * answer (`undefined` for a 204).
 *
 * Without a session, sends to the sign-in page; on a 401, ends the session; on
 * a 403 `password_change_required`, sends to the password change page. Any
 * other error is raised as an `AdminApiError`.
 */
export async function callWithSession<T>(
  path: string,
  write?: AdminApiWrite,
): Promise<T> {
  const { token } = await getSession();
  if (!token) {
    redirect("/login");
  }
  try {
    return await callWithToken<T>(path, token, write);
  } catch (error) {
    if (error instanceof AdminApiError) {
      if (error.status === 401) {
        // The session ended on the admin API: expired, signed out, or disabled account.
        redirect(SESSION_EXPIRED_PATH);
      }
      if (error.code === PASSWORD_CHANGE_REQUIRED) {
        redirect(CHANGE_PASSWORD_PATH);
      }
    }
    throw error;
  }
}

/**
 * Call the admin API with an explicit session token. Every error, a 401
 * included, is raised as an `AdminApiError`: nothing redirects.
 */
export async function callWithToken<T>(
  path: string,
  token: string,
  write?: AdminApiWrite,
): Promise<T> {
  return readBody<T>(await callAdminApi(path, token, write));
}

/**
 * Call a route of the admin API that needs no session: the setup of the first
 * account, the sign-in and the account recovery. Errors are raised as an
 * `AdminApiError`.
 */
export async function callWithoutSession<T>(
  path: string,
  write?: AdminApiWrite,
): Promise<T> {
  return readBody<T>(await callAdminApi(path, null, write));
}

async function callAdminApi(
  path: string,
  token: string | null,
  write?: AdminApiWrite,
): Promise<Response> {
  const { adminApiUrl } = readDashboardConfig();
  const headers: Record<string, string> = { Accept: "application/json" };
  // The admin API limits sign-ins per address: give it the browser's, not ours.
  const address = await browserAddress();
  if (address !== null) {
    headers["X-Forwarded-For"] = address;
  }
  if (token !== null) {
    headers.Authorization = `Bearer ${token}`;
  }
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
  if (response.status === 204) {
    return undefined as T;
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
  return new AdminApiError(
    message,
    response.status,
    code,
    parseRetryAfter(response.headers.get("retry-after")),
  );
}

/**
 * Seconds to wait from a `Retry-After` header: a number of seconds, or an HTTP
 * date. Null when the header is missing or invalid.
 */
export function parseRetryAfter(
  value: string | null,
  now: number = Date.now(),
): number | null {
  if (value === null || value.trim() === "") {
    return null;
  }
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed);
  }
  // An HTTP date starts with the name of a day ("Fri, 23 Oct 2026 ...").
  if (!/^[A-Za-z]/.test(trimmed)) {
    return null;
  }
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) {
    return null;
  }
  return Math.max(0, Math.ceil((date - now) / 1000));
}

/**
 * The address of the browser that made the current request, or null.
 *
 * Next.js puts it first in `X-Forwarded-For` (behind a reverse proxy, the
 * proxy does). Null outside a request, for example during the build.
 */
async function browserAddress(): Promise<string | null> {
  try {
    const forwardedFor = (await requestHeaders()).get("x-forwarded-for");
    const first = forwardedFor?.split(",")[0]?.trim();
    return first ? first : null;
  } catch {
    return null;
  }
}

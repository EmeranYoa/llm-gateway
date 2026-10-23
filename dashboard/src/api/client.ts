import "server-only";

import { redirect } from "next/navigation";

import { readDashboardConfig } from "@/lib/config";
import { getSession } from "@/lib/session";

import type { paths } from "./schema";

/**
 * Client of the admin API, used only by the Next.js server.
 *
 * The admin key lives in the encrypted session cookie. This module reads it on
 * the server and sends it to the admin API: the browser never sees it.
 */

export type Me =
  paths["/admin/v1/me"]["get"]["responses"][200]["content"]["application/json"];

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

/** Return the operator who owns the admin key of the session. */
export async function getMe(): Promise<Me> {
  return getWithSession<Me>("/admin/v1/me");
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

async function getWithSession<T>(path: string): Promise<T> {
  const { adminKey } = await getSession();
  if (!adminKey) {
    redirect("/login");
  }
  const response = await callAdminApi(path, adminKey);
  if (response.status === 401) {
    // The key was revoked, or expired from the admin API's point of view.
    redirect(SESSION_EXPIRED_PATH);
  }
  return readBody<T>(response);
}

async function callAdminApi(path: string, adminKey: string): Promise<Response> {
  const { adminApiUrl } = readDashboardConfig();
  try {
    return await fetch(`${adminApiUrl}${path}`, {
      headers: {
        Authorization: `Bearer ${adminKey}`,
        Accept: "application/json",
      },
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

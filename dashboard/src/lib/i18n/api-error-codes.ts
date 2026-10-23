import type { KnownErrorCode } from "./api-errors";

/**
 * Every error `code` the admin API can return, plus `admin_api_unreachable`,
 * which the API client of the dashboard makes when the admin API cannot be
 * reached (`src/api/client.ts`).
 *
 * `openapi.json` does not list them (the `code` of an error is any string), so
 * this list is kept by hand. To keep it in sync, list the codes of the admin
 * API from the root of the repository:
 *
 *   grep -rhoE 'code="[a-z_]+"' app/admin_api | sort -u
 *
 * The compiler checks that each code here has an English message
 * (`apiError.codes` in `messages/en.ts`). `api-errors.test.ts` checks that each
 * one has a message in every language, and that this list matches the codes
 * of the Python sources when they are next to the dashboard.
 */
export const ADMIN_API_ERROR_CODES = [
  "admin_api_unreachable",
  "authentication_unavailable",
  "cannot_disable_self",
  "database_unavailable",
  "invalid_credentials",
  "invalid_cursor",
  "invalid_password",
  "invalid_recovery_token",
  "invalid_session",
  "invalid_setup_token",
  "key_already_revoked",
  "key_not_found",
  "last_enabled_operator",
  "operator_exists",
  "operator_not_found",
  "password_change_required",
  "reauthentication_failed",
  "recovery_disabled",
  "recovery_used",
  "redis_unavailable",
  "request_not_found",
  "setup_closed",
  "tenant_not_found",
  "too_many_attempts",
  "use_own_password_change",
] as const satisfies readonly KnownErrorCode[];

/** The codes made by the dashboard itself, not by the admin API. */
export const DASHBOARD_ERROR_CODES: readonly string[] = [
  "admin_api_unreachable",
];

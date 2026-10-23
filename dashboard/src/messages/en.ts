import type { MessageTree } from "./types";

/**
 * English texts of the dashboard: the reference dictionary.
 *
 * Every other language (`fr.ts`) must have exactly these keys; the compiler
 * checks it. Read a message with `t("nav.overview")` (see `lib/i18n`).
 *
 * - `{name}` is a placeholder, filled by `t(key, { name })`.
 * - An object with `one` / `other` is a plural message, chosen by `count`:
 *   `t("some.key", { count: 3 })`. `{count}` is written with the number format
 *   of the language.
 */
export const en = {
  app: {
    title: "LLM Gateway admin",
    description: "Usage, costs and keys of the LLM gateway.",
  },
  nav: {
    label: "Main",
    overview: "Overview",
    tenants: "Tenants",
    providers: "Providers",
    requests: "Requests",
    keys: "Keys",
    signOut: "Sign out",
  },
  language: {
    label: "Language",
  },
  session: {
    expired:
      "Your session has ended: the admin key was refused. Sign in again.",
  },
  apiError: {
    title: "The admin API returned an error.",
    generic: "The admin API could not complete the request.",
    englishDetail: "Details: {detail}",
    /** One message per `code` of the admin API errors (OpenAI format). */
    codes: {
      admin_api_unreachable:
        "The admin API cannot be reached. Check that it is running.",
      authentication_unavailable:
        "The admin key cannot be checked right now. Try again later.",
      database_unavailable: "The database is unavailable. Try again later.",
      invalid_api_key: "The admin key is missing or invalid.",
      invalid_credentials: "Wrong sign-in details.",
      invalid_cursor:
        "This page of results is no longer valid. Go back to the first page.",
      invalid_session: "Your session is no longer valid. Sign in again.",
      invalid_setup_token: "This setup link is invalid or has expired.",
      key_already_revoked: "This API key is already revoked.",
      key_not_found: "This API key does not exist.",
      password_change_required: "Change your password to continue.",
      redis_unavailable: "Redis is unavailable. Try again later.",
      request_not_found: "No request with this id.",
      setup_closed: "The first setup is already done. Sign in instead.",
      tenant_not_found: "This tenant does not exist.",
    },
  },
  format: {
    noValue: "n/a",
    unknown: "unknown",
    noLimit: "no limit",
    quota: "{used} / {limit}",
    lessThan: "< {amount}",
    milliseconds: "{value} ms",
    seconds: "{value} s",
    minutes: "{value} min",
    minutesSeconds: "{minutes} min {seconds} s",
    hours: "{value} h",
    ago: "{duration} ago",
  },
} as const satisfies MessageTree;

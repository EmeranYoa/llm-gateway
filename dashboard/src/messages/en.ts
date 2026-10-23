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
    saveFailed: "The language could not be saved in your account.",
  },
  session: {
    expired: "Your session has ended. Sign in again.",
  },
  /** Fields and checks shared by the sign-in, setup, password and recovery forms. */
  auth: {
    username: "Username",
    password: "Password",
    passwordAgain: "Password again",
    currentPassword: "Current password",
    newPassword: "New password",
    newPasswordAgain: "New password again",
    passwordRule: "At least 12 characters, different from the username.",
    tokenHint: "Printed in the admin API logs:",
    problems: {
      missingFields: "Fill in every field.",
      passwordsDiffer: "The two passwords are different.",
      passwordTooShort: "The password must have at least 12 characters.",
    },
    tooManyAttemptsWait: "Too many sign-in attempts. Try again in {wait}.",
  },
  signIn: {
    title: "Sign in",
    intro: "Sign in with your operator account.",
    submit: "Sign in",
    recoveryLink: "Lost every password? Recover an account",
  },
  setup: {
    title: "Create the first account",
    intro:
      "No operator account exists yet. Create the first one with the setup token.",
    token: "Setup token",
    submit: "Create the account",
  },
  changePassword: {
    title: "Change your password",
    required: "Choose a new password before you continue.",
    submit: "Change the password",
  },
  recovery: {
    title: "Recover an account",
    intro:
      "Set a new password for an account with the recovery token. You will choose another one at sign-in.",
    token: "Recovery token",
    submit: "Set the new password",
    done: "The password of {username} is set. Sign in with it: you will then choose another one.",
    signInLink: "Go to sign-in",
    banner:
      "Account recovery is on. Once you are back in, remove OPERATOR_RECOVERY from the admin API settings and restart it.",
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
        "Sign-in cannot be checked right now. Try again later.",
      database_unavailable: "The database is unavailable. Try again later.",
      invalid_credentials: "Wrong username or password.",
      invalid_cursor:
        "This page of results is no longer valid. Go back to the first page.",
      invalid_password:
        "This password is refused: use at least 12 characters, different from the username.",
      invalid_recovery_token:
        "Wrong recovery token. Copy it again from the admin API logs.",
      invalid_session: "Your session is no longer valid. Sign in again.",
      invalid_setup_token:
        "Wrong setup token. Copy it again from the admin API logs.",
      key_already_revoked: "This API key is already revoked.",
      key_not_found: "This API key does not exist.",
      operator_not_found: "No operator account has this username.",
      password_change_required: "Change your password to continue.",
      reauthentication_failed: "The current password is wrong.",
      recovery_disabled:
        "Account recovery is off. Start the admin API with OPERATOR_RECOVERY=true to use it.",
      recovery_used:
        "The recovery token has been used already. Restart the admin API to get a new one.",
      redis_unavailable: "Redis is unavailable. Try again later.",
      request_not_found: "No request with this id.",
      setup_closed: "The first account exists already. Sign in instead.",
      tenant_not_found: "This tenant does not exist.",
      too_many_attempts: "Too many sign-in attempts. Try again later.",
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

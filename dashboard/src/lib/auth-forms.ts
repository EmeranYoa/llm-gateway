/**
 * The forms of the sign-in, setup, password change and recovery screens: their
 * fields, their checks, and the errors they show.
 *
 * Pure functions, used twice: in the browser, to answer at once without calling
 * the server, and again in the server actions, which never trust the browser.
 * The admin API checks the password rules a last time (`invalid_password`).
 */

import type { components } from "@/api/schema";

type PasswordChangeRequest = components["schemas"]["OwnPasswordChange"];
type RecoveryRequest = components["schemas"]["RecoveryRequest"];

/** The admin API refuses shorter passwords. */
export const MIN_PASSWORD_LENGTH = 12;

/** A form the browser or the server refused before calling the admin API. */
export type FormProblem =
  "missingFields" | "passwordsDiffer" | "passwordTooShort";

/**
 * Why a form failed: a check of the form, or an error of the admin API. The
 * form translates it (`describeAuthError`). `message` is the English message
 * of the admin API: it never contains a password or a token.
 */
export type AuthFormError =
  | { kind: "form"; problem: FormProblem }
  | {
      kind: "api";
      code: string | null;
      message: string;
      retryAfterSeconds: number | null;
    };

/** What a form gets back from its server action when it does not redirect. */
export type AuthFormState = { error: AuthFormError | null };

/** The state of the recovery form: done when `recoveredUsername` is set. */
export type RecoveryFormState = AuthFormState & {
  recoveredUsername: string | null;
};

export type Checked<T> =
  { ok: true; value: T } | { ok: false; error: AuthFormError };

/** The names of the password fields: they are emptied after an error. */
export const PASSWORD_FIELDS = [
  "password",
  "passwordAgain",
  "currentPassword",
  "newPassword",
  "newPasswordAgain",
] as const;

export function checkSignInForm(
  form: FormData,
): Checked<components["schemas"]["SignInRequest"]> {
  const username = text(form, "username").trim();
  const password = text(form, "password");
  if (username === "" || password === "") {
    return refused("missingFields");
  }
  return { ok: true, value: { username, password } };
}

export function checkSetupForm(
  form: FormData,
): Checked<components["schemas"]["SetupRequest"]> {
  const token = text(form, "token").trim();
  const username = text(form, "username").trim();
  const password = checkNewPassword(form, "password", "passwordAgain");
  if (token === "" || username === "") {
    return refused("missingFields");
  }
  if (!password.ok) {
    return password;
  }
  return { ok: true, value: { token, username, password: password.value } };
}

export function checkPasswordChangeForm(
  form: FormData,
): Checked<PasswordChangeRequest> {
  const current = text(form, "currentPassword");
  const password = checkNewPassword(form, "newPassword", "newPasswordAgain");
  if (current === "") {
    return refused("missingFields");
  }
  if (!password.ok) {
    return password;
  }
  return {
    ok: true,
    value: { current_password: current, new_password: password.value },
  };
}

export function checkRecoveryForm(form: FormData): Checked<RecoveryRequest> {
  const token = text(form, "token").trim();
  const username = text(form, "username").trim();
  const password = checkNewPassword(form, "newPassword", "newPasswordAgain");
  if (token === "" || username === "") {
    return refused("missingFields");
  }
  if (!password.ok) {
    return password;
  }
  return {
    ok: true,
    value: { token, username, new_password: password.value },
  };
}

/**
 * A new password typed twice: both filled, equal, and long enough. Passwords
 * are never trimmed: a space is a character like any other.
 */
export function checkNewPassword(
  form: FormData,
  field: string,
  againField: string,
): Checked<string> {
  const password = text(form, field);
  const again = text(form, againField);
  if (password === "" || again === "") {
    return refused("missingFields");
  }
  if (password !== again) {
    return refused("passwordsDiffer");
  }
  // Characters, not UTF-16 units: the admin API counts them the same way.
  if ([...password].length < MIN_PASSWORD_LENGTH) {
    return refused("passwordTooShort");
  }
  return { ok: true, value: password };
}

function text(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

/** A form refused before calling the admin API. */
export function refused(problem: FormProblem): {
  ok: false;
  error: AuthFormError;
} {
  return { ok: false, error: { kind: "form", problem } };
}

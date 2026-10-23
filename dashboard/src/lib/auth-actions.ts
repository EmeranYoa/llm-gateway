"use server";

import { redirect } from "next/navigation";

import { AdminApiError } from "@/api/client";
import {
  changePassword,
  type OpenedSession,
  recoverAccount,
  setUpFirstAccount,
  signIn,
  signOut,
} from "@/api/operators";
import {
  type AuthFormError,
  type AuthFormState,
  checkPasswordChangeForm,
  checkRecoveryForm,
  checkSetupForm,
  checkSignInForm,
  type RecoveryFormState,
} from "@/lib/auth-forms";
import { getSession } from "@/lib/session";

/**
 * Sign-in, setup of the first account, sign-out, password change and account
 * recovery, as server actions.
 *
 * Passwords and tokens are posted once by a form and sent to the admin API.
 * The session token it returns goes into the encrypted session cookie only: no
 * action returns a password or a token, and none puts one in a URL. A success
 * ends with a redirect; an error comes back as a code for the form to translate.
 */

export async function signInAction(
  _previous: AuthFormState,
  form: FormData,
): Promise<AuthFormState> {
  const checked = checkSignInForm(form);
  if (!checked.ok) {
    return { error: checked.error };
  }
  const opened = await openSession(() => signIn(checked.value));
  if ("error" in opened) {
    return opened;
  }
  redirect("/");
}

export async function setUpAction(
  _previous: AuthFormState,
  form: FormData,
): Promise<AuthFormState> {
  const checked = checkSetupForm(form);
  if (!checked.ok) {
    return { error: checked.error };
  }
  const opened = await openSession(() => setUpFirstAccount(checked.value));
  if ("error" in opened) {
    return opened;
  }
  redirect("/");
}

/** Change the password of the signed-in operator, then open the overview. */
export async function changePasswordAction(
  _previous: AuthFormState,
  form: FormData,
): Promise<AuthFormState> {
  const checked = checkPasswordChangeForm(form);
  if (!checked.ok) {
    return { error: checked.error };
  }
  try {
    await changePassword(checked.value);
  } catch (error) {
    return { error: apiFailure(error) };
  }
  redirect("/");
}

/**
 * Set a new password with the recovery token. The operator then signs in with
 * it, and must change it at once (the admin API sets `must_change_password`).
 */
export async function recoverAction(
  _previous: RecoveryFormState,
  form: FormData,
): Promise<RecoveryFormState> {
  const checked = checkRecoveryForm(form);
  if (!checked.ok) {
    return { error: checked.error, recoveredUsername: null };
  }
  try {
    const { username } = await recoverAccount(checked.value);
    return { error: null, recoveredUsername: username };
  } catch (error) {
    return { error: apiFailure(error), recoveredUsername: null };
  }
}

/**
 * End the session on the admin API, then in the cookie. A failure of the admin
 * API is ignored: the cookie is destroyed anyway, and the session expires on
 * the admin API by itself.
 */
export async function signOutAction(): Promise<void> {
  const session = await getSession();
  if (session.token) {
    await signOut(session.token).catch(() => {});
  }
  session.destroy();
  redirect("/login");
}

// --- Helpers ---

/** Open a session with the admin API and keep its token in the cookie only. */
async function openSession(
  open: () => Promise<OpenedSession>,
): Promise<{ ok: true } | { error: AuthFormError }> {
  let opened: OpenedSession;
  try {
    opened = await open();
  } catch (error) {
    return { error: apiFailure(error) };
  }
  const session = await getSession();
  session.token = opened.token;
  await session.save();
  return { ok: true };
}

/** An error of the admin API, for the form; anything else (redirects, bugs) goes on. */
function apiFailure(error: unknown): AuthFormError {
  if (!(error instanceof AdminApiError)) {
    throw error;
  }
  return {
    kind: "api",
    code: error.code,
    message: error.message,
    retryAfterSeconds: error.retryAfterSeconds,
  };
}

import "server-only";

import { cache } from "react";

import { callWithoutSession, callWithSession, callWithToken } from "./client";
import type { components } from "./schema";

type LanguageUpdate = components["schemas"]["LanguageChoice"];
type PasswordChangeRequest = components["schemas"]["OwnPasswordChange"];
type RecoveryRequest = components["schemas"]["RecoveryRequest"];
type RecoveryResult = components["schemas"]["RecoveredOperator"];
type RecoveryStatus = components["schemas"]["RecoveryStatus"];

/**
 * Calls of the admin API about operator accounts: setup of the first account,
 * sign-in and sign-out, password change, language, and account recovery.
 *
 * Server only, like `client.ts`. Passwords and tokens go from a server action
 * to the admin API, and the session token comes back into the session cookie:
 * none of them is ever returned to the browser.
 */

type Schemas = components["schemas"];

/** A session opened by the admin API. `token` goes into the session cookie only. */
export type OpenedSession = Schemas["Session"];
export type SetupRequest = Schemas["SetupRequest"];
export type SignInRequest = Schemas["SignInRequest"];

/** Whether the first account can still be created. Read once per request. */
export const getSetupStatus = cache(async (): Promise<boolean> => {
  const status =
    await callWithoutSession<Schemas["SetupStatus"]>("/admin/v1/setup");
  return status.open;
});

/** Create the first operator account with the setup token, and sign it in. */
export async function setUpFirstAccount(
  request: SetupRequest,
): Promise<OpenedSession> {
  return callWithoutSession<OpenedSession>("/admin/v1/setup", {
    method: "POST",
    body: request,
  });
}

/** Open a session. A wrong username or password raises a 401 `invalid_credentials`. */
export async function signIn(request: SignInRequest): Promise<OpenedSession> {
  return callWithoutSession<OpenedSession>("/admin/v1/sessions", {
    method: "POST",
    body: request,
  });
}

/** End the session of `token` on the admin API: the token is refused from then on. */
export async function signOut(token: string): Promise<void> {
  await callWithToken<void>("/admin/v1/sessions/current", token, {
    method: "DELETE",
  });
}

/** Change the password of the signed-in operator. Clears `must_change_password`. */
export async function changePassword(
  request: PasswordChangeRequest,
): Promise<void> {
  await callWithSession<unknown>("/admin/v1/me/password", {
    method: "PUT",
    body: request,
  });
}

/** Save the language of the signed-in operator's account. */
export async function setAccountLanguage(
  language: LanguageUpdate["language"],
): Promise<void> {
  const body: LanguageUpdate = { language };
  await callWithSession<unknown>("/admin/v1/me/language", {
    method: "PUT",
    body,
  });
}

/**
 * Whether account recovery is enabled (`OPERATOR_RECOVERY` set on the admin
 * API). Read once per request: the banner and the sign-in page both need it.
 */
export const getRecoveryStatus = cache(async (): Promise<boolean> => {
  const status = await callWithoutSession<RecoveryStatus>("/admin/v1/recovery");
  return status.enabled;
});

/** Set a new password with the recovery token. The operator must change it at sign-in. */
export async function recoverAccount(
  request: RecoveryRequest,
): Promise<RecoveryResult> {
  return callWithoutSession<RecoveryResult>("/admin/v1/recovery", {
    method: "POST",
    body: request,
  });
}

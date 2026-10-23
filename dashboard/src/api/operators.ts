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
 * sign-in and sign-out, password change, language, account recovery, and the
 * management of the operator accounts (Operators screen).
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
/** An operator account as listed by the admin API. Never its password nor its hash. */
export type OperatorAccount = Schemas["Operator"];
export type NewOperatorRequest = Schemas["NewOperatorRequest"];
export type PasswordResetRequest = Schemas["PasswordResetRequest"];
/** The current password of the signed-in operator, which confirms an action on accounts. */
export type Reauthentication = Schemas["Reauthentication"];

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

/** Every operator account, enabled or not, in alphabetical order. */
export async function listOperators(): Promise<OperatorAccount[]> {
  const list = await callWithSession<Schemas["Operators"]>(
    "/admin/v1/operators",
  );
  return list.operators;
}

/**
 * Create an operator account; its owner must change the password at the first
 * sign-in. A taken username raises a 409 `operator_exists`.
 */
export async function createOperator(
  request: NewOperatorRequest,
): Promise<OperatorAccount> {
  return callWithSession<OperatorAccount>("/admin/v1/operators", {
    method: "POST",
    body: request,
  });
}

/**
 * Give another operator a new password, which they must change at the next
 * sign-in. Their sessions are closed. One's own password is changed with
 * `changePassword` instead (400 `use_own_password_change`).
 */
export async function resetOperatorPassword(
  operatorId: number,
  request: PasswordResetRequest,
): Promise<OperatorAccount> {
  return callWithSession<OperatorAccount>(
    `${operatorPath(operatorId)}/reset-password`,
    { method: "POST", body: request },
  );
}

/**
 * Disable an operator account and close its sessions. The admin API refuses
 * to disable oneself (`cannot_disable_self`) or the last enabled account
 * (`last_enabled_operator`).
 */
export async function disableOperator(
  operatorId: number,
  request: Reauthentication,
): Promise<OperatorAccount> {
  return callWithSession<OperatorAccount>(
    `${operatorPath(operatorId)}/disable`,
    { method: "POST", body: request },
  );
}

/** Enable an operator account again: it can sign in with its password. */
export async function enableOperator(
  operatorId: number,
  request: Reauthentication,
): Promise<OperatorAccount> {
  return callWithSession<OperatorAccount>(
    `${operatorPath(operatorId)}/enable`,
    { method: "POST", body: request },
  );
}

function operatorPath(operatorId: number): string {
  return `/admin/v1/operators/${operatorId}`;
}

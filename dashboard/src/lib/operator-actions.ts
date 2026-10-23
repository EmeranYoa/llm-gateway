"use server";

import { revalidatePath } from "next/cache";

import { AdminApiError } from "@/api/client";
import {
  changePassword,
  createOperator,
  disableOperator,
  enableOperator,
  resetOperatorPassword,
} from "@/api/operators";
import { type AuthFormError, checkPasswordChangeForm } from "@/lib/auth-forms";
import {
  checkNewOperatorForm,
  checkPasswordResetForm,
  checkReauthenticationForm,
  type OperatorFormState,
  type OwnPasswordFormState,
} from "@/lib/operator-forms";

/**
 * The writes of the Operators screen, as server actions.
 *
 * Each one checks the form again (the browser is never trusted), sends it with
 * the current password of the operator to the admin API, then revalidates the
 * Operators page so the list shows the new data. Passwords go from the form to
 * the admin API only: an action returns an error code or a username, never a
 * password, and none puts one in a URL.
 */

const OPERATORS_PATH = "/operators";

export async function createOperatorAction(
  _previous: OperatorFormState,
  form: FormData,
): Promise<OperatorFormState> {
  const checked = checkNewOperatorForm(form);
  if (!checked.ok) {
    return { error: checked.error, done: null };
  }
  return changeAccount(() => createOperator(checked.value));
}

export async function resetOperatorPasswordAction(
  _previous: OperatorFormState,
  form: FormData,
): Promise<OperatorFormState> {
  const checked = checkPasswordResetForm(form);
  if (!checked.ok) {
    return { error: checked.error, done: null };
  }
  const { operatorId, request } = checked.value;
  return changeAccount(() => resetOperatorPassword(operatorId, request));
}

export async function disableOperatorAction(
  _previous: OperatorFormState,
  form: FormData,
): Promise<OperatorFormState> {
  const checked = checkReauthenticationForm(form);
  if (!checked.ok) {
    return { error: checked.error, done: null };
  }
  const { operatorId, request } = checked.value;
  return changeAccount(() => disableOperator(operatorId, request));
}

export async function enableOperatorAction(
  _previous: OperatorFormState,
  form: FormData,
): Promise<OperatorFormState> {
  const checked = checkReauthenticationForm(form);
  if (!checked.ok) {
    return { error: checked.error, done: null };
  }
  const { operatorId, request } = checked.value;
  return changeAccount(() => enableOperator(operatorId, request));
}

/**
 * Change the password of the signed-in operator. Their other sessions are
 * closed by the admin API; this one stays open, so the page stays.
 */
export async function changeOwnPasswordAction(
  _previous: OwnPasswordFormState,
  form: FormData,
): Promise<OwnPasswordFormState> {
  const checked = checkPasswordChangeForm(form);
  if (!checked.ok) {
    return { error: checked.error, changed: false };
  }
  try {
    await changePassword(checked.value);
    return { error: null, changed: true };
  } catch (error) {
    return { error: apiFailure(error), changed: false };
  } finally {
    revalidatePath(OPERATORS_PATH);
  }
}

// --- Helpers ---

/**
 * Run a call that changes an account, then revalidate the Operators page.
 *
 * The page is revalidated after an error too: a 404 or a refused disable
 * means the list is stale (an account changed by another operator).
 */
async function changeAccount(
  call: () => Promise<{ username: string }>,
): Promise<OperatorFormState> {
  try {
    const { username } = await call();
    return { error: null, done: { username } };
  } catch (error) {
    return { error: apiFailure(error), done: null };
  } finally {
    revalidatePath(OPERATORS_PATH);
  }
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

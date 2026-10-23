/**
 * The forms of the Operators screen: their checks, their results, and which
 * actions each account offers.
 *
 * Pure functions, used twice: in the browser, to answer at once without calling
 * the server, and again in the server actions, which never trust the browser.
 * Every action on accounts asks for the current password of the signed-in
 * operator (`currentPassword`), which the admin API checks.
 */

import type { components } from "@/api/schema";

import {
  type AuthFormState,
  type Checked,
  checkNewPassword,
  refused,
} from "./auth-forms";

type Schemas = components["schemas"];

/** An operator account as listed by the admin API. Never its password nor its hash. */
export type Operator = Schemas["Operator"];

/**
 * What a form of the Operators screen gets back from its server action: an
 * error, or the username of the account it changed. Never a password.
 */
export type OperatorFormState = AuthFormState & {
  done: { username: string } | null;
};

/** What the "change my password" form gets back from its server action. */
export type OwnPasswordFormState = AuthFormState & { changed: boolean };

/** An action on one account, with the id of that account. */
export type OperatorChange<T> = { operatorId: number; request: T };

/** The actions a row of the list can offer. */
export type OperatorActionKind = "reset" | "disable" | "enable";

/** Create an account: a username, its first password twice, and your password. */
export function checkNewOperatorForm(
  form: FormData,
): Checked<Schemas["NewOperatorRequest"]> {
  const username = field(form, "username").trim();
  const current = field(form, "currentPassword");
  const password = checkNewPassword(form, "password", "passwordAgain");
  if (username === "" || current === "") {
    return refused("missingFields");
  }
  if (!password.ok) {
    return password;
  }
  return {
    ok: true,
    value: { username, password: password.value, current_password: current },
  };
}

/** Reset the password of another account: the new password twice, and yours. */
export function checkPasswordResetForm(
  form: FormData,
): Checked<OperatorChange<Schemas["PasswordResetRequest"]>> {
  const operatorId = readOperatorId(form);
  const current = field(form, "currentPassword");
  const password = checkNewPassword(form, "password", "passwordAgain");
  if (operatorId === null || current === "") {
    return refused("missingFields");
  }
  if (!password.ok) {
    return password;
  }
  return {
    ok: true,
    value: {
      operatorId,
      request: { password: password.value, current_password: current },
    },
  };
}

/** Disable or enable an account: its id, and your password. */
export function checkReauthenticationForm(
  form: FormData,
): Checked<OperatorChange<Schemas["Reauthentication"]>> {
  const operatorId = readOperatorId(form);
  const current = field(form, "currentPassword");
  if (operatorId === null || current === "") {
    return refused("missingFields");
  }
  return {
    ok: true,
    value: { operatorId, request: { current_password: current } },
  };
}

/**
 * The actions offered on an account of the list.
 *
 * - None on your own account: you change your password with its own form, and
 *   you cannot disable yourself.
 * - "disable" is hidden for the last enabled account: nobody could sign in.
 *
 * The admin API checks the same rules, and its errors are shown if it refuses.
 */
export function operatorActions(
  operator: Operator,
  currentUsername: string | null,
  operators: readonly Operator[],
): OperatorActionKind[] {
  if (operator.username === currentUsername) {
    return [];
  }
  if (!operator.enabled) {
    return ["reset", "enable"];
  }
  const enabledCount = operators.filter((account) => account.enabled).length;
  return enabledCount > 1 ? ["reset", "disable"] : ["reset"];
}

function readOperatorId(form: FormData): number | null {
  const text = field(form, "operatorId");
  const id = Number(text);
  return /^\d+$/.test(text) && Number.isSafeInteger(id) ? id : null;
}

function field(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

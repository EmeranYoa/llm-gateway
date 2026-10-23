"use server";

import { revalidatePath } from "next/cache";

import { AdminApiError } from "@/api/client";
import {
  type AdminActionPage,
  clearCache,
  createKey,
  type CreatedKey,
  listActions,
  revokeKey,
  setTenantLimits,
} from "@/api/tenant-keys";
import {
  type Checked,
  checkCacheClearForm,
  checkLimitsForm,
  checkNewKeyForm,
  checkRevokeForm,
  type KeyFormError,
} from "@/lib/key-forms";

/**
 * The writes of the Keys screen, as server actions.
 *
 * Each one checks the form again (the browser is never trusted), calls the admin
 * API through the server-only client, then revalidates the Keys page so it shows
 * the new data. Errors come back as codes for the form to translate
 * (`describeKeyError`); a 401 ends the session (the client redirects).
 *
 * The full key returned by `createKeyAction` goes back to the form that asked for
 * it, and nowhere else: it is not written to the session, a cookie or the URL.
 */

const KEYS_PATH = "/keys";

export type ActionError = { status: "error"; error: KeyFormError };
type Idle = { status: "idle" };

export type CreateKeyState =
  Idle | ActionError | { status: "created"; key: CreatedKey };

export type RevokeKeyState =
  Idle | ActionError | { status: "revoked"; prefix: string };

export type LimitsState = Idle | ActionError | { status: "saved" };

export type CacheClearState =
  | Idle
  | ActionError
  | {
      status: "cleared";
      removed: number;
      tenant: string;
      alias: string | null;
    };

export type LoadActionsResult =
  ActionError | { status: "loaded"; page: AdminActionPage };

export async function createKeyAction(
  _previous: CreateKeyState,
  form: FormData,
): Promise<CreateKeyState> {
  const checked = checkNewKeyForm(form);
  if (!checked.ok) {
    return invalid(checked);
  }
  return write(async () => ({
    status: "created",
    key: await createKey(checked.value),
  }));
}

export async function revokeKeyAction(
  _previous: RevokeKeyState,
  form: FormData,
): Promise<RevokeKeyState> {
  const checked = checkRevokeForm(form);
  if (!checked.ok) {
    return invalid(checked);
  }
  return write(async () => {
    const revoked = await revokeKey(checked.value);
    return { status: "revoked", prefix: revoked.prefix };
  });
}

export async function setLimitsAction(
  _previous: LimitsState,
  form: FormData,
): Promise<LimitsState> {
  const checked = checkLimitsForm(form);
  if (!checked.ok) {
    return invalid(checked);
  }
  const { tenant, limits } = checked.value;
  return write(async () => {
    await setTenantLimits(tenant, limits);
    return { status: "saved" };
  });
}

export async function clearCacheAction(
  _previous: CacheClearState,
  form: FormData,
): Promise<CacheClearState> {
  const checked = checkCacheClearForm(form);
  if (!checked.ok) {
    return invalid(checked);
  }
  const { tenant, alias } = checked.value;
  return write(async () => {
    const { removed } = await clearCache(
      alias === null ? { tenant } : { tenant, alias },
    );
    return { status: "cleared", removed, tenant, alias };
  });
}

/** The next, older page of the history of admin actions. Reads only. */
export async function loadActionsAction(
  before: number,
): Promise<LoadActionsResult> {
  if (!Number.isSafeInteger(before)) {
    return {
      status: "error",
      error: { kind: "form", problem: "noMoreActions" },
    };
  }
  try {
    return { status: "loaded", page: await listActions(before) };
  } catch (error) {
    return failure(error);
  }
}

// --- Helpers ---

function invalid(
  checked: Extract<Checked<unknown>, { ok: false }>,
): ActionError {
  return { status: "error", error: checked.error };
}

/**
 * Run a call that changes data, then revalidate the Keys page.
 *
 * The page is revalidated after an error too: a 404 or 409 means the page shows
 * stale data (a tenant or key changed by someone else).
 */
async function write<S>(call: () => Promise<S>): Promise<S | ActionError> {
  try {
    return await call();
  } catch (error) {
    return failure(error);
  } finally {
    revalidatePath(KEYS_PATH);
  }
}

/** An error of the admin API, for the form; anything else (redirects, bugs) goes on. */
function failure(error: unknown): ActionError {
  if (!(error instanceof AdminApiError)) {
    throw error;
  }
  return {
    status: "error",
    error: {
      kind: "api",
      status: error.status,
      code: error.code,
      message: error.message,
    },
  };
}

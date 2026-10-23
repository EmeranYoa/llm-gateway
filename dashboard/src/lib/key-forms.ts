/**
 * Read and check the forms of the Keys screen.
 *
 * Shared by the browser (to answer at once, without a round trip) and by the
 * server actions (which never trust the browser). Upper bounds are left to the
 * admin API, whose validation errors are shown with their English detail.
 *
 * Errors are codes, not texts: the form translates them (`describeKeyError`
 * in `lib/i18n/key-errors.ts`).
 */

/** A limit of a tenant, as named in the forms and the admin API. */
export type LimitField = "rpm" | "tokens_per_day";

/** Why a form was refused before calling the admin API. */
export type KeyFormProblem =
  | {
      problem:
        | "missingTenantName"
        | "noTenantSelected"
        | "noLimitGiven"
        | "missingKeyId"
        | "noMoreActions";
    }
  | { problem: "notWholeNumber" | "tooLarge"; field: LimitField };

/**
 * Why a form of the Keys screen failed: a check of the form, or an error of the
 * admin API. `message` is the English message of the admin API, shown as a
 * detail when its `code` has no translation.
 */
export type KeyFormError =
  | ({ kind: "form" } & KeyFormProblem)
  | {
      kind: "api";
      status: number | null;
      code: string | null;
      message: string;
    };

export type Checked<T> =
  { ok: true; value: T } | { ok: false; error: KeyFormError };

export type LimitsInput = { rpm?: number; tokens_per_day?: number };

/** The limits filled in: positive whole numbers. Empty fields are left out. */
function readLimits(form: FormData): Checked<LimitsInput> {
  const limits: LimitsInput = {};
  for (const field of ["rpm", "tokens_per_day"] as const) {
    const text = String(form.get(field) ?? "").trim();
    if (text === "") {
      continue;
    }
    const value = Number(text);
    if (!/^\d+$/.test(text) || value <= 0) {
      return refused({ problem: "notWholeNumber", field });
    }
    if (!Number.isSafeInteger(value)) {
      return refused({ problem: "tooLarge", field });
    }
    limits[field] = value;
  }
  return { ok: true, value: limits };
}

function readText(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

function refused(problem: KeyFormProblem): { ok: false; error: KeyFormError } {
  return { ok: false, error: { kind: "form", ...problem } };
}

/** Create a key: a tenant name, and optional limits. */
export function checkNewKeyForm(
  form: FormData,
): Checked<{ tenant: string } & LimitsInput> {
  const tenant = readText(form, "tenant");
  if (tenant === "") {
    return refused({ problem: "missingTenantName" });
  }
  const limits = readLimits(form);
  if (!limits.ok) {
    return limits;
  }
  return { ok: true, value: { tenant, ...limits.value } };
}

/** Change limits: a tenant name and at least one limit. */
export function checkLimitsForm(
  form: FormData,
): Checked<{ tenant: string; limits: LimitsInput }> {
  const tenant = readText(form, "tenant");
  if (tenant === "") {
    return refused({ problem: "noTenantSelected" });
  }
  const limits = readLimits(form);
  if (!limits.ok) {
    return limits;
  }
  if (Object.keys(limits.value).length === 0) {
    return refused({ problem: "noLimitGiven" });
  }
  return { ok: true, value: { tenant, limits: limits.value } };
}

/** Clear the cache: a tenant name, and optionally one alias. */
export function checkCacheClearForm(
  form: FormData,
): Checked<{ tenant: string; alias: string | null }> {
  const tenant = readText(form, "tenant");
  if (tenant === "") {
    return refused({ problem: "noTenantSelected" });
  }
  const alias = readText(form, "alias");
  return { ok: true, value: { tenant, alias: alias === "" ? null : alias } };
}

/** Revoke a key: the id of the key. */
export function checkRevokeForm(form: FormData): Checked<number> {
  const text = readText(form, "keyId");
  const keyId = Number(text);
  if (!/^\d+$/.test(text) || !Number.isSafeInteger(keyId)) {
    return refused({ problem: "missingKeyId" });
  }
  return { ok: true, value: keyId };
}

/**
 * Read and check the forms of the Keys screen.
 *
 * Shared by the browser (to answer at once, without a round trip) and by the
 * server actions (which never trust the browser). Upper bounds are left to the
 * admin API, whose validation errors are shown as they are.
 */

export type Checked<T> = { ok: true; value: T } | { ok: false; error: string };

export type LimitsInput = { rpm?: number; tokens_per_day?: number };

const LIMIT_LABELS = {
  rpm: "Requests per minute",
  tokens_per_day: "Tokens per day",
} as const;

/** The limits filled in: positive whole numbers. Empty fields are left out. */
function readLimits(form: FormData): Checked<LimitsInput> {
  const limits: LimitsInput = {};
  for (const name of ["rpm", "tokens_per_day"] as const) {
    const text = String(form.get(name) ?? "").trim();
    if (text === "") {
      continue;
    }
    const value = Number(text);
    if (!/^\d+$/.test(text) || value <= 0) {
      return {
        ok: false,
        error: `${LIMIT_LABELS[name]} must be a whole number greater than 0.`,
      };
    }
    if (!Number.isSafeInteger(value)) {
      return { ok: false, error: `${LIMIT_LABELS[name]} is too large.` };
    }
    limits[name] = value;
  }
  return { ok: true, value: limits };
}

function readText(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

/** Create a key: a tenant name, and optional limits. */
export function checkNewKeyForm(
  form: FormData,
): Checked<{ tenant: string } & LimitsInput> {
  const tenant = readText(form, "tenant");
  if (tenant === "") {
    return { ok: false, error: "Enter the name of a tenant." };
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
    return { ok: false, error: "No tenant is selected." };
  }
  const limits = readLimits(form);
  if (!limits.ok) {
    return limits;
  }
  if (Object.keys(limits.value).length === 0) {
    return {
      ok: false,
      error: "Give at least one limit: requests per minute or tokens per day.",
    };
  }
  return { ok: true, value: { tenant, limits: limits.value } };
}

/** Clear the cache: a tenant name, and optionally one alias. */
export function checkCacheClearForm(
  form: FormData,
): Checked<{ tenant: string; alias: string | null }> {
  const tenant = readText(form, "tenant");
  if (tenant === "") {
    return { ok: false, error: "No tenant is selected." };
  }
  const alias = readText(form, "alias");
  return { ok: true, value: { tenant, alias: alias === "" ? null : alias } };
}

/** Revoke a key: the id of the key. */
export function checkRevokeForm(form: FormData): Checked<number> {
  const text = readText(form, "keyId");
  const keyId = Number(text);
  if (!/^\d+$/.test(text) || !Number.isSafeInteger(keyId)) {
    return {
      ok: false,
      error: "This key cannot be revoked: its id is missing.",
    };
  }
  return { ok: true, value: keyId };
}

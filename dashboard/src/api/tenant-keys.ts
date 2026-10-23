import "server-only";

import { callWithSession } from "./client";
import type { components } from "./schema";

/**
 * Calls of the admin API behind the Keys screen: tenants, their keys and limits,
 * their cached answers, and the history of admin actions.
 *
 * Server only, like `client.ts`: the admin key of the session is added there.
 */

type Schemas = components["schemas"];

export type TenantKeys = Schemas["TenantKeys"];
export type ApiKey = Schemas["ApiKey"];
export type Limits = Schemas["Limits"];
export type TenantLimitsView = Schemas["TenantLimitsView"];
export type NewKeyRequest = Schemas["NewKeyRequest"];
export type CreatedKey = Schemas["CreatedKey"];
export type LimitsUpdate = Schemas["LimitsUpdate"];
export type CacheClearRequest = Schemas["CacheClearRequest"];
export type CacheClearResult = Schemas["CacheClearResult"];
export type AdminAction = Schemas["AdminAction"];
export type AdminActionPage = Schemas["AdminActionPage"];

/** Admin actions loaded at once by the history. */
export const ACTIONS_PAGE_SIZE = 20;

export async function getTenantKeys(tenant: string): Promise<TenantKeys> {
  return callWithSession<TenantKeys>(
    `/admin/v1/tenants/${encodeURIComponent(tenant)}/keys`,
  );
}

export async function createKey(request: NewKeyRequest): Promise<CreatedKey> {
  return callWithSession<CreatedKey>("/admin/v1/keys", {
    method: "POST",
    body: request,
  });
}

export async function revokeKey(keyId: number): Promise<ApiKey> {
  return callWithSession<ApiKey>(`/admin/v1/keys/${keyId}/revoke`, {
    method: "POST",
  });
}

export async function setTenantLimits(
  tenant: string,
  limits: LimitsUpdate,
): Promise<TenantLimitsView> {
  return callWithSession<TenantLimitsView>(
    `/admin/v1/tenants/${encodeURIComponent(tenant)}/limits`,
    { method: "PUT", body: limits },
  );
}

export async function clearCache(
  request: CacheClearRequest,
): Promise<CacheClearResult> {
  return callWithSession<CacheClearResult>("/admin/v1/cache/clear", {
    method: "POST",
    body: request,
  });
}

/** One page of the history, newest first; `before` is the `next_before` of the previous page. */
export async function listActions(before?: number): Promise<AdminActionPage> {
  const query = new URLSearchParams({ limit: String(ACTIONS_PAGE_SIZE) });
  if (before !== undefined) {
    query.set("before", String(before));
  }
  return callWithSession<AdminActionPage>(`/admin/v1/actions?${query}`);
}

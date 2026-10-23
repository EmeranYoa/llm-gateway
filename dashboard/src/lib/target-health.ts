/**
 * Why the gateway sends traffic to a target, or elsewhere, right now: read from
 * the live state of the target (`GET /admin/v1/targets`).
 */

import type { components } from "@/api/schema";

type TargetReport = components["schemas"]["TargetReport"];
type TargetLiveState = components["schemas"]["TargetLiveState"];

export type TargetHealth =
  | "healthy"
  | "cooling_down"
  | "breaker_open"
  | "half_open"
  | "quota_full"
  | "live_unknown"
  | "removed";

export const TARGET_HEALTH_LABELS: Record<TargetHealth, string> = {
  healthy: "Healthy",
  cooling_down: "Cooling down",
  breaker_open: "Breaker open",
  half_open: "Breaker half-open",
  quota_full: "Quota full",
  live_unknown: "Live state unavailable (Redis)",
  removed: "No longer configured",
};

export const TARGET_HEALTH_DEFINITIONS: Record<TargetHealth, string> = {
  healthy:
    "No cooldown, breaker closed, quotas not full: the target gets traffic.",
  cooling_down:
    "A 429 or a misconfiguration error started a cooldown: the target is skipped until it ends.",
  breaker_open:
    "Too many failures opened the circuit breaker: the target is skipped until it turns half-open.",
  half_open:
    "The breaker lets one trial call through. Its result closes the breaker again or opens it.",
  quota_full:
    "A requests or tokens quota is used up: the target is skipped until the window frees room.",
  live_unknown:
    "Redis cannot be read: cooldowns, breakers and used quotas are unknown. The gateway routes without them (degraded mode).",
  removed:
    "This target is in no route any more. It is shown because it has usage in the period.",
};

/** The quotas used up right now: `RPM`, `TPM`, `RPD`. */
export function fullQuotas(live: TargetLiveState): string[] {
  const quotas = [
    ["RPM", live.rpm],
    ["TPM", live.tpm],
    ["RPD", live.rpd],
  ] as const;
  return quotas
    .filter(
      ([, quota]) =>
        quota.limit !== null &&
        quota.used !== null &&
        quota.used >= quota.limit,
    )
    .map(([name]) => name);
}

/**
 * Every reason why the target gets traffic or not, most blocking first.
 * `healthy` comes alone, when nothing keeps traffic away.
 */
export function targetHealth(target: TargetReport): TargetHealth[] {
  const live = target.live;
  if (!target.configured) {
    return ["removed"];
  }
  if (live === null || live.status === "unknown") {
    return ["live_unknown"];
  }
  const reasons: TargetHealth[] = [];
  if (live.cooldown?.active) {
    reasons.push("cooling_down");
  }
  if (live.breaker?.state === "open") {
    reasons.push("breaker_open");
  }
  if (fullQuotas(live).length > 0) {
    reasons.push("quota_full");
  }
  if (live.breaker?.state === "half_open") {
    reasons.push("half_open");
  }
  return reasons.length > 0 ? reasons : ["healthy"];
}

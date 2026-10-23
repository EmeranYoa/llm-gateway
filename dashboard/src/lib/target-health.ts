/**
 * Why the gateway sends traffic to a target, or elsewhere, right now: read from
 * the live state of the target (`GET /admin/v1/targets`).
 */

import type { components } from "@/api/schema";

type TargetReport = components["schemas"]["TargetReport"];
type TargetLiveState = components["schemas"]["TargetLiveState"];

/**
 * Why a target gets traffic or not. Each one has a label and a definition in
 * the dictionaries: `targetHealth.labels.<health>`, `targetHealth.definitions.<health>`.
 */
export type TargetHealth =
  | "healthy"
  | "cooling_down"
  | "breaker_open"
  | "half_open"
  | "quota_full"
  | "live_unknown"
  | "removed";

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

/**
 * How the screens show the outcome of one usage row (one step of a routing
 * path). Outcomes come from the usage log: see `Outcome` in
 * `app/routing/router.py`, plus `cache_hit` and `rejected_tenant_quota`.
 */

import type { components } from "@/api/schema";

type RoutingStep = components["schemas"]["RoutingStep"];

/**
 * The kind of an outcome, which gives its colour:
 * - `success`: the answer came from here;
 * - `error`: the target failed; the gateway tried the next one (except for a
 *   stream interrupted after its first token);
 * - `skipped`: the gateway did not call the target and tried the next one;
 * - `client_error`: the request itself was refused, or the client left.
 */
export type OutcomeKind = "success" | "error" | "skipped" | "client_error";

export const OUTCOME_KIND_LABELS: Record<OutcomeKind, string> = {
  success: "Success",
  error: "Error",
  skipped: "Skipped",
  client_error: "Client error",
};

export type OutcomeDescription = {
  kind: OutcomeKind;
  /** What happened, in a few words. */
  label: string;
};

const OUTCOMES: Record<string, OutcomeDescription> = {
  success: { kind: "success", label: "Answered" },
  cache_hit: { kind: "success", label: "Answered from the cache" },
  rate_limited: { kind: "error", label: "Rate limited (429)" },
  unavailable: { kind: "error", label: "Unavailable (5xx or network error)" },
  timeout: { kind: "error", label: "Timeout" },
  misconfigured: {
    kind: "error",
    label: "Misconfigured (401, 403 or 404)",
  },
  interrupted: {
    kind: "error",
    label: "Stream interrupted after its first token",
  },
  skipped_cooldown: { kind: "skipped", label: "Cooldown active" },
  skipped_breaker: { kind: "skipped", label: "Circuit breaker open" },
  skipped_quota: { kind: "skipped", label: "Quota full" },
  invalid_request: { kind: "client_error", label: "Invalid request (4xx)" },
  cancelled: { kind: "client_error", label: "Cancelled by the client" },
  rejected_tenant_quota: {
    kind: "client_error",
    label: "Tenant quota exceeded (429)",
  },
};

/** The kind and label of the outcome of a step of a routing path. */
export function describeOutcome(
  step: Pick<RoutingStep, "outcome" | "latency_ms">,
): OutcomeDescription {
  if (step.outcome === "context_too_large") {
    // Without a duration, the gateway found the request too large before
    // calling the target; with one, the provider refused it.
    return step.latency_ms === null
      ? { kind: "skipped", label: "Too large for this target" }
      : { kind: "error", label: "Context too large (refused by the provider)" };
  }
  return OUTCOMES[step.outcome] ?? { kind: "error", label: step.outcome };
}

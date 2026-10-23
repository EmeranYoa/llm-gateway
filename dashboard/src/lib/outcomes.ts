/**
 * How the screens show the outcome of one usage row (one step of a routing
 * path). Outcomes come from the usage log: see `Outcome` in
 * `app/routing/router.py`, plus `cache_hit` and `rejected_tenant_quota`.
 */

import type { components } from "@/api/schema";
import type { en } from "@/messages/en";

import type { Locale } from "./i18n/locale";
import { getTranslator } from "./i18n/translator";

type RoutingStep = components["schemas"]["RoutingStep"];

/**
 * The kind of an outcome, which gives its colour and its badge
 * (`outcomes.kinds` in the dictionaries):
 * - `success`: the answer came from here;
 * - `error`: the target failed; the gateway tried the next one (except for a
 *   stream interrupted after its first token);
 * - `skipped`: the gateway did not call the target and tried the next one;
 * - `client_error`: the request itself was refused, or the client left.
 */
export type OutcomeKind = "success" | "error" | "skipped" | "client_error";

export type OutcomeDescription = {
  kind: OutcomeKind;
  /** What happened, in a few words, in the language of the page. */
  label: string;
};

/** The key of a label in `outcomes.labels` of the dictionaries. */
type OutcomeLabel = keyof typeof en.outcomes.labels;

const OUTCOMES: Record<string, { kind: OutcomeKind; label: OutcomeLabel }> = {
  success: { kind: "success", label: "success" },
  cache_hit: { kind: "success", label: "cache_hit" },
  rate_limited: { kind: "error", label: "rate_limited" },
  unavailable: { kind: "error", label: "unavailable" },
  timeout: { kind: "error", label: "timeout" },
  misconfigured: { kind: "error", label: "misconfigured" },
  interrupted: { kind: "error", label: "interrupted" },
  skipped_cooldown: { kind: "skipped", label: "skipped_cooldown" },
  skipped_breaker: { kind: "skipped", label: "skipped_breaker" },
  skipped_quota: { kind: "skipped", label: "skipped_quota" },
  invalid_request: { kind: "client_error", label: "invalid_request" },
  cancelled: { kind: "client_error", label: "cancelled" },
  rejected_tenant_quota: {
    kind: "client_error",
    label: "rejected_tenant_quota",
  },
};

/** The kind and label of the outcome of a step of a routing path. */
export function describeOutcome(
  step: Pick<RoutingStep, "outcome" | "latency_ms">,
  locale: Locale,
): OutcomeDescription {
  const t = getTranslator(locale);
  if (step.outcome === "context_too_large") {
    // Without a duration, the gateway found the request too large before
    // calling the target; with one, the provider refused it.
    return step.latency_ms === null
      ? {
          kind: "skipped",
          label: t("outcomes.labels.context_too_large_skipped"),
        }
      : {
          kind: "error",
          label: t("outcomes.labels.context_too_large_refused"),
        };
  }
  if (!Object.hasOwn(OUTCOMES, step.outcome)) {
    // An outcome added to the gateway after this dashboard: shown as it is.
    return { kind: "error", label: step.outcome };
  }
  const { kind, label } = OUTCOMES[step.outcome];
  return { kind, label: t(`outcomes.labels.${label}`) };
}

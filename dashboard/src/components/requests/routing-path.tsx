import type { RoutingStep } from "@/api/client";
import { Badge, type BadgeTone } from "@/components/badge";
import {
  formatCount,
  formatDuration,
  formatMoney,
  formatSimilarity,
} from "@/lib/format";
import {
  describeOutcome,
  OUTCOME_KIND_LABELS,
  type OutcomeKind,
} from "@/lib/outcomes";

const KIND_TONES: Record<OutcomeKind, BadgeTone> = {
  success: "green",
  error: "red",
  skipped: "slate",
  client_error: "amber",
};

/** The colour of the number of a step, on the line of the timeline. */
const KIND_DOTS: Record<OutcomeKind, string> = {
  success: "bg-emerald-600 text-white",
  error: "bg-red-600 text-white",
  skipped: "bg-slate-300 text-slate-800",
  client_error: "bg-amber-500 text-slate-900",
};

/** Prompt and completion tokens, and the estimate reserved before the call. */
function formatTokens(step: RoutingStep): string | null {
  const parts: string[] = [];
  if (step.prompt_tokens !== null) {
    parts.push(`${formatCount(step.prompt_tokens)} prompt`);
  }
  if (step.completion_tokens !== null) {
    parts.push(`${formatCount(step.completion_tokens)} completion`);
  }
  if (step.estimated_tokens !== null) {
    parts.push(`${formatCount(step.estimated_tokens)} estimated`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}

/** The figures of one step; only those it has, so a skip stays short. */
function StepDetails({ step }: { step: RoutingStep }) {
  const called = step.latency_ms !== null;
  const tokens = formatTokens(step);
  return (
    <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
      {step.status_code !== null && (
        <Detail label="HTTP status" value={step.status_code} />
      )}
      {called && (
        <Detail label="Latency" value={formatDuration(step.latency_ms)} />
      )}
      {step.first_token_ms !== null && (
        <Detail
          label="First token"
          value={formatDuration(step.first_token_ms)}
        />
      )}
      {tokens !== null && <Detail label="Tokens" value={tokens} />}
      {called && step.outcome !== "cache_hit" && (
        <Detail label="Cost" value={formatMoney(step.cost_usd)} />
      )}
      {step.saved_cost_usd !== null && (
        <Detail label="Saved cost" value={formatMoney(step.saved_cost_usd)} />
      )}
      {step.cache !== null && <Detail label="Cache" value={step.cache} />}
      {step.cache_similarity !== null && (
        <Detail
          label="Similarity"
          value={
            step.cache_similarity === 1
              ? "1 (identical request)"
              : formatSimilarity(step.cache_similarity)
          }
        />
      )}
    </dl>
  );
}

function StepTarget({ step }: { step: RoutingStep }) {
  if (step.provider === null || step.model === null) {
    return <span className="text-slate-600">No target examined</span>;
  }
  return (
    <span className="font-mono text-sm break-all">
      <span className="text-slate-500">{step.provider}/</span>
      {step.model}
    </span>
  );
}

/**
 * The routing path of a request: every target examined, in order, with what
 * happened to it. The colour of a step follows its kind (success, error,
 * skipped, client error), always written next to it.
 */
export function RoutingPath({ steps }: { steps: RoutingStep[] }) {
  return (
    <ol aria-label="Routing path" className="flex flex-col">
      {steps.map((step, position) => {
        const { kind, label } = describeOutcome(step);
        const last = position === steps.length - 1;
        return (
          <li
            key={step.attempt_index}
            aria-label={`Step ${step.attempt_index + 1}`}
            className="relative flex gap-3 pb-4"
          >
            {!last && (
              <span
                aria-hidden="true"
                className="absolute top-7 bottom-0 left-3 w-px bg-slate-300"
              />
            )}
            <span
              aria-hidden="true"
              className={`relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${KIND_DOTS[kind]}`}
            >
              {step.attempt_index + 1}
            </span>
            <div className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <StepTarget step={step} />
                <Badge tone={KIND_TONES[kind]}>
                  {OUTCOME_KIND_LABELS[kind]}
                </Badge>
                <span className="text-sm text-slate-700">{label}</span>
                {step.degraded && (
                  <Badge
                    tone="orange"
                    title="The gateway routed without Redis: no quota, cooldown or breaker checks."
                  >
                    Degraded mode
                  </Badge>
                )}
              </div>
              <StepDetails step={step} />
              {step.error_message && (
                <p className="mt-2 rounded bg-slate-50 px-2 py-1 font-mono text-xs break-words text-slate-700">
                  {step.error_message}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

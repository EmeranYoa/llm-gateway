import type { RoutingStep } from "@/api/client";
import { Badge, type BadgeTone } from "@/components/badge";
import { formatDuration, formatMoney, formatSimilarity } from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";
import { describeOutcome, type OutcomeKind } from "@/lib/outcomes";

import { cacheLabel } from "./request-status-badge";

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
function formatTokens(locale: Locale, step: RoutingStep): string | null {
  const t = getTranslator(locale);
  const parts: string[] = [];
  if (step.prompt_tokens !== null) {
    parts.push(t("routingPath.promptTokens", { tokens: step.prompt_tokens }));
  }
  if (step.completion_tokens !== null) {
    parts.push(
      t("routingPath.completionTokens", { tokens: step.completion_tokens }),
    );
  }
  if (step.estimated_tokens !== null) {
    parts.push(
      t("routingPath.estimatedTokens", { tokens: step.estimated_tokens }),
    );
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
function StepDetails({ step, locale }: { step: RoutingStep; locale: Locale }) {
  const t = getTranslator(locale);
  const called = step.latency_ms !== null;
  const tokens = formatTokens(locale, step);
  return (
    <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
      {step.status_code !== null && (
        <Detail label={t("routingPath.httpStatus")} value={step.status_code} />
      )}
      {called && (
        <Detail
          label={t("routingPath.latency")}
          value={formatDuration(locale, step.latency_ms)}
        />
      )}
      {step.first_token_ms !== null && (
        <Detail
          label={t("routingPath.firstToken")}
          value={formatDuration(locale, step.first_token_ms)}
        />
      )}
      {tokens !== null && (
        <Detail label={t("routingPath.tokens")} value={tokens} />
      )}
      {called && step.outcome !== "cache_hit" && (
        <Detail
          label={t("routingPath.cost")}
          value={formatMoney(locale, step.cost_usd)}
        />
      )}
      {step.saved_cost_usd !== null && (
        <Detail
          label={t("routingPath.savedCost")}
          value={formatMoney(locale, step.saved_cost_usd)}
        />
      )}
      {step.cache !== null && (
        <Detail
          label={t("routingPath.cache")}
          value={cacheLabel(step.cache, locale)}
        />
      )}
      {step.cache_similarity !== null && (
        <Detail
          label={t("routingPath.similarity")}
          value={
            step.cache_similarity === 1
              ? t("routingPath.identical")
              : formatSimilarity(locale, step.cache_similarity)
          }
        />
      )}
    </dl>
  );
}

function StepTarget({ step, locale }: { step: RoutingStep; locale: Locale }) {
  if (step.provider === null || step.model === null) {
    return (
      <span className="text-slate-600">
        {getTranslator(locale)("routingPath.noTarget")}
      </span>
    );
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
export function RoutingPath({
  steps,
  locale,
}: {
  steps: RoutingStep[];
  locale: Locale;
}) {
  const t = getTranslator(locale);
  return (
    <ol aria-label={t("routingPath.label")} className="flex flex-col">
      {steps.map((step, position) => {
        const { kind, label } = describeOutcome(step, locale);
        const last = position === steps.length - 1;
        return (
          <li
            key={step.attempt_index}
            aria-label={t("routingPath.step", {
              number: step.attempt_index + 1,
            })}
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
                <StepTarget step={step} locale={locale} />
                <Badge tone={KIND_TONES[kind]}>
                  {t(`outcomes.kinds.${kind}`)}
                </Badge>
                <span className="text-sm text-slate-700">{label}</span>
                {step.degraded && (
                  <Badge
                    tone="orange"
                    title={t("routingPath.degradedDefinition")}
                  >
                    {t("routingPath.degraded")}
                  </Badge>
                )}
              </div>
              <StepDetails step={step} locale={locale} />
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

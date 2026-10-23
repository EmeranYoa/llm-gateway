import type {
  Overview,
  RequestDetail,
  RequestPage,
  RequestSummary,
  RoutingStep,
  TargetReport,
  TargetsReport,
  TenantStatisticsList,
} from "@/api/client";

/** Answers of the admin API used by the page tests. */

export function overviewFixture(changes: Partial<Overview> = {}): Overview {
  return {
    period: "24h",
    tenant: null,
    start: "2026-10-22T12:00:00Z",
    end: "2026-10-23T12:00:00Z",
    requests: 1250,
    answered: 1200,
    failed: 25,
    client_error: 20,
    cancelled: 5,
    error_rate: 0.02,
    fallback_rate: 0.125,
    latency_ms: { p50: 850, p95: 2140 },
    time_to_first_token_ms: { p50: 320, p95: 900 },
    cache_hit_latency_ms: { p50: 12 },
    tokens: 345678,
    cost_usd: 1.5,
    unpriced_requests: 0,
    cache_requests: 400,
    cache_hits: 100,
    cache_hit_rate: 0.25,
    saved_tokens: 23456,
    saved_cost_usd: 0.42,
    series: [
      {
        start: "2026-10-23T10:00:00Z",
        requests: 50,
        answered: 48,
        failed: 2,
        cost_usd: 0.06,
        cache_hits: 4,
      },
      {
        start: "2026-10-23T11:00:00Z",
        requests: 60,
        answered: 60,
        failed: 0,
        cost_usd: 0.07,
        cache_hits: 5,
      },
    ],
    ...changes,
  };
}

export function tenantsFixture(
  changes: Partial<TenantStatisticsList> = {},
): TenantStatisticsList {
  return {
    period: "24h",
    start: "2026-10-22T12:00:00Z",
    end: "2026-10-23T12:00:00Z",
    tenants: [
      {
        tenant: "acme",
        requests: 1000,
        tokens: 300000,
        cost_usd: 1.25,
        unpriced_requests: 0,
        error_rate: 0.015,
        cache_hits: 80,
        saved_cost_usd: 0.4,
        quota_refusals: 3,
      },
      {
        tenant: "beta & co",
        requests: 0,
        tokens: 0,
        cost_usd: 0,
        unpriced_requests: 0,
        error_rate: 0,
        cache_hits: 0,
        saved_cost_usd: 0,
        quota_refusals: 0,
      },
    ],
    ...changes,
  };
}

type TargetLiveState = NonNullable<TargetReport["live"]>;

/** The live state of a target with no cooldown, a closed breaker and room in its quotas. */
export function liveFixture(
  changes: Partial<TargetLiveState> = {},
): TargetLiveState {
  return {
    status: "known",
    cooldown: { active: false, until: null },
    breaker: { state: "closed", open_until: null, trial_running: false },
    rpm: { used: 12, limit: 30 },
    tpm: { used: 1500, limit: 8000 },
    rpd: { used: 400, limit: 1000, resets_at: "2026-10-24T00:00:00Z" },
    ...changes,
  };
}

export function targetFixture(
  changes: Partial<TargetReport> = {},
): TargetReport {
  return {
    provider: "groq",
    model: "openai/gpt-oss-20b",
    configured: true,
    statistics: {
      calls: 200,
      success: 180,
      rate_limited: 10,
      timeout: 3,
      unavailable: 4,
      misconfigured: 0,
      invalid_request: 2,
      context_too_large: 1,
      interrupted: 1,
      cancelled: 2,
      skipped_cooldown: 25,
      skipped_breaker: 5,
      skipped_quota: 7,
      success_rate: 0.9,
      latency_p50_ms: 640,
      latency_p95_ms: 1800,
    },
    live: liveFixture(),
    ...changes,
  };
}

export function targetsFixture(
  changes: Partial<TargetsReport> = {},
): TargetsReport {
  return { period: "24h", targets: [targetFixture()], ...changes };
}

export function requestSummaryFixture(
  changes: Partial<RequestSummary> = {},
): RequestSummary {
  return {
    request_id: "req-1",
    created_at: "2026-10-23T11:59:30Z",
    tenant: "acme",
    alias: "chat-fast",
    status: "answered",
    status_code: 200,
    provider: "gemini",
    model: "gemini-2.5-flash",
    attempts: 3,
    stream: true,
    latency_ms: 1250,
    cost_usd: 0.0012,
    cache: "miss",
    ...changes,
  };
}

export function requestPageFixture(
  changes: Partial<RequestPage> = {},
): RequestPage {
  return {
    items: [
      requestSummaryFixture(),
      requestSummaryFixture({
        request_id: "req-2",
        created_at: "2026-10-23T11:58:00Z",
        tenant: null,
        status: "failed",
        status_code: 503,
        provider: null,
        model: null,
        attempts: 2,
        stream: false,
        latency_ms: null,
        cost_usd: null,
        cache: null,
      }),
    ],
    next_cursor: null,
    ...changes,
  };
}

export function routingStepFixture(
  changes: Partial<RoutingStep> = {},
): RoutingStep {
  return {
    attempt_index: 0,
    provider: "groq",
    model: "openai/gpt-oss-20b",
    outcome: "success",
    status_code: 200,
    latency_ms: 800,
    first_token_ms: null,
    estimated_tokens: 600,
    prompt_tokens: 120,
    completion_tokens: 80,
    cost_usd: 0.0001,
    saved_cost_usd: null,
    degraded: false,
    cache: null,
    cache_similarity: null,
    error_message: null,
    ...changes,
  };
}

/** A streamed request: a cooldown skip, a 429, then an answer from the third target. */
export function requestDetailFixture(
  changes: Partial<RequestDetail> = {},
): RequestDetail {
  return {
    ...requestSummaryFixture(),
    routing_path: [
      routingStepFixture({
        outcome: "skipped_cooldown",
        status_code: null,
        latency_ms: null,
        estimated_tokens: null,
        prompt_tokens: null,
        completion_tokens: null,
        cost_usd: null,
        cache: "miss",
        error_message: "Cooldown active for 42 s",
      }),
      routingStepFixture({
        attempt_index: 1,
        provider: "openrouter",
        model: "meta-llama/llama-3.3-70b-instruct:free",
        outcome: "rate_limited",
        status_code: 429,
        latency_ms: 150,
        prompt_tokens: null,
        completion_tokens: null,
        cost_usd: null,
        cache: "miss",
        error_message:
          "openrouter/meta-llama/llama-3.3-70b-instruct:free: Rate limit exceeded",
      }),
      routingStepFixture({
        attempt_index: 2,
        provider: "gemini",
        model: "gemini-2.5-flash",
        latency_ms: 1100,
        first_token_ms: 420,
        cost_usd: 0.0012,
        cache: "miss",
      }),
    ],
    ...changes,
  };
}

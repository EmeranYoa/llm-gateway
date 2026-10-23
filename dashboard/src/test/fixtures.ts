import type { Overview, TenantStatisticsList } from "@/api/client";

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
        error_rate: 0,
        cache_hits: 0,
        saved_cost_usd: 0,
        quota_refusals: 0,
      },
    ],
    ...changes,
  };
}

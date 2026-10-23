/**
 * Exact definitions of the figures of the dashboard, shown in tooltips.
 *
 * They follow the admin API (`app/admin_api/statistics.py` and
 * `app/admin_api/request_status.py`). Each request has one status: answered,
 * failed, client error or cancelled.
 */
export const DEFINITIONS = {
  requests:
    "Requests received in the period, tenant quota refusals included. Each request counts once, whatever the number of targets it tried.",
  errorRate:
    "Failed requests / requests. A request failed when it got no answer because of the gateway or the providers: every target failed or was skipped (503), the deadline passed (504), or a stream was interrupted after its first token. Client errors (invalid request, tenant quota, too large for every target) and cancelled requests are not failures.",
  fallbackRate:
    "Share of the requests answered by a provider (not from the cache) whose answer came from a fallback target, not from the first target of the alias.",
  latency:
    "Duration of the requests answered by a provider, all their attempts included. p50 is the median, p95 the 95th percentile.",
  timeToFirstToken:
    "Time to the first content of the streamed answers (stream: true). p50 is the median, p95 the 95th percentile.",
  cacheHitLatency:
    "Median duration of the requests answered from the cache (lookup time).",
  tokens:
    "Prompt and completion tokens of the answers of providers. Cache hits spend no tokens and are not counted.",
  cost: "Cost of every attempt that has a price. Requests answered by a model without a price, or without token counts from the provider, are not included: they are counted apart, never as free.",
  cacheHitRate:
    "Cache hits / requests to an alias that uses the cache. 0 when no request used the cache.",
  cacheHits: "Requests answered from the cache, without calling a provider.",
  savedTokens:
    "Tokens the cache hits did not spend: the token usage of the original answers they replayed.",
  savedCost: "What the cache hits would have cost if a provider had answered.",
  quotaRefusals:
    "Requests refused by the tenant's own quota (requests per minute or daily token budget): HTTP 429.",
  targetCalls:
    "Real calls to the provider in the period. Skips (cooldown, breaker, quota) and requests too large for the target are not calls.",
  targetSuccessRate:
    "Successful calls / calls. n/a when the target was not called in the period.",
  targetLatency:
    "Duration of the successful calls of this target. p50 is the median, p95 the 95th percentile.",
  targetFailures:
    "Calls that failed, by reason. After a 429, a timeout, an unavailable or a misconfigured target, the gateway tries the next target of the alias.",
  targetSkips:
    "Times the gateway did not call this target and tried the next one: cooldown active, circuit breaker open, or quota full.",
  targetRequestErrors:
    "Not a problem of the target: the provider refused the request (4xx), or the request was too large for this target (checked before the call, or refused by the provider). A too large request is tried on the next target.",
  cooldown:
    "After a 429 or a misconfiguration error, the target is skipped until the cooldown ends.",
  breaker:
    "Closed: calls go through. Open: too many failures, the target is skipped until the open time ends. Half-open: one trial call decides whether it closes again.",
  rpm: "Requests in the last 60 s, against the requests-per-minute limit of the configuration.",
  tpm: "Tokens reserved or used in the last 60 s, against the tokens-per-minute limit of the configuration.",
  rpd: "Requests since the provider's last daily reset, against the requests-per-day limit of the configuration.",
} as const;

/** What each status of a request means (see `app/admin_api/request_status.py`). */
export const REQUEST_STATUS_DEFINITIONS = {
  answered: "The client got an answer, from a provider or from the cache.",
  failed:
    "No answer because of the gateway or the providers: every target failed or was skipped (503), the deadline passed (504), or a stream was interrupted after its first token.",
  client_error:
    "The request itself was refused: invalid request (4xx from the provider), tenant quota exceeded (429), or too large for every target (400).",
  cancelled: "The client left before the answer ended.",
} as const;

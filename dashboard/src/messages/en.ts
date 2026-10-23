import type { MessageTree } from "./types";

/**
 * English texts of the dashboard: the reference dictionary.
 *
 * Every other language (`fr.ts`) must have exactly these keys; the compiler
 * checks it. Read a message with `t("nav.overview")` (see `lib/i18n`).
 *
 * - `{name}` is a placeholder, filled by `t(key, { name })`.
 * - An object with `one` / `other` is a plural message, chosen by `count`:
 *   `t("some.key", { count: 3 })`. `{count}` is written with the number format
 *   of the language.
 */
export const en = {
  app: {
    title: "LLM Gateway admin",
    description: "Usage, costs and keys of the LLM gateway.",
  },
  nav: {
    label: "Main",
    overview: "Overview",
    tenants: "Tenants",
    providers: "Providers",
    requests: "Requests",
    keys: "Keys",
    signOut: "Sign out",
  },
  language: {
    label: "Language",
    saveFailed: "The language could not be saved in your account.",
  },
  session: {
    expired: "Your session has ended. Sign in again.",
  },
  /** Fields and checks shared by the sign-in, setup, password and recovery forms. */
  auth: {
    username: "Username",
    password: "Password",
    passwordAgain: "Password again",
    currentPassword: "Current password",
    newPassword: "New password",
    newPasswordAgain: "New password again",
    passwordRule: "At least 12 characters, different from the username.",
    tokenHint: "Printed in the admin API logs:",
    problems: {
      missingFields: "Fill in every field.",
      passwordsDiffer: "The two passwords are different.",
      passwordTooShort: "The password must have at least 12 characters.",
    },
    tooManyAttemptsWait: "Too many sign-in attempts. Try again in {wait}.",
  },
  signIn: {
    title: "Sign in",
    intro: "Sign in with your operator account.",
    submit: "Sign in",
    recoveryLink: "Lost every password? Recover an account",
  },
  setup: {
    title: "Create the first account",
    intro:
      "No operator account exists yet. Create the first one with the setup token.",
    token: "Setup token",
    submit: "Create the account",
  },
  changePassword: {
    title: "Change your password",
    required: "Choose a new password before you continue.",
    submit: "Change the password",
  },
  recovery: {
    title: "Recover an account",
    intro:
      "Set a new password for an account with the recovery token. You will choose another one at sign-in.",
    token: "Recovery token",
    submit: "Set the new password",
    done: "The password of {username} is set. Sign in with it: you will then choose another one.",
    signInLink: "Go to sign-in",
    banner:
      "Account recovery is on. Once you are back in, remove OPERATOR_RECOVERY from the admin API settings and restart it.",
  },
  apiError: {
    title: "The admin API returned an error.",
    generic: "The admin API could not complete the request.",
    englishDetail: "Details: {detail}",
    /** One message per `code` of the admin API errors (OpenAI format). */
    codes: {
      admin_api_unreachable:
        "The admin API cannot be reached. Check that it is running.",
      authentication_unavailable:
        "Sign-in cannot be checked right now. Try again later.",
      cannot_disable_self: "You cannot disable your own account.",
      database_unavailable: "The database is unavailable. Try again later.",
      invalid_credentials: "Wrong username or password.",
      invalid_cursor:
        "This page of results is no longer valid. Go back to the first page.",
      invalid_password:
        "This password is refused: use at least 12 characters, different from the username.",
      invalid_recovery_token:
        "Wrong recovery token. Copy it again from the admin API logs.",
      invalid_session: "Your session is no longer valid. Sign in again.",
      invalid_setup_token:
        "Wrong setup token. Copy it again from the admin API logs.",
      key_already_revoked: "This API key is already revoked.",
      key_not_found: "This API key does not exist.",
      last_enabled_operator:
        "This is the last enabled account: it cannot be disabled, or nobody could sign in.",
      operator_exists: "An operator account with this username exists already.",
      operator_not_found: "This operator account does not exist.",
      password_change_required: "Change your password to continue.",
      reauthentication_failed: "The current password is wrong.",
      recovery_disabled:
        "Account recovery is off. Start the admin API with OPERATOR_RECOVERY=true to use it.",
      recovery_used:
        "The recovery token has been used already. Restart the admin API to get a new one.",
      redis_unavailable: "Redis is unavailable. Try again later.",
      request_not_found: "No request with this id.",
      setup_closed: "The first account exists already. Sign in instead.",
      tenant_not_found: "This tenant does not exist.",
      too_many_attempts: "Too many sign-in attempts. Try again later.",
      use_own_password_change:
        "To change your own password, use “Change my password”.",
    },
  },
  /** The Operators screen: the accounts that can sign in to the dashboard. */
  operators: {
    nav: "Operators",
    title: "Operators",
    intro:
      "The accounts that can sign in to this dashboard. Every change asks for your current password again.",
    listTitle: "Accounts",
    timeZone: "Last sign-in times in {zone}.",
    empty: "No operator account.",
    columns: {
      username: "Username",
      status: "Status",
      lastSignIn: "Last sign-in",
      actions: "Actions",
    },
    you: "you",
    enabled: "Enabled",
    enabledHint: "Can sign in.",
    disabled: "Disabled",
    disabledHint: "Cannot sign in until the account is enabled again.",
    mustChangePassword: "Must change password",
    mustChangePasswordHint:
      "Must choose a new password at the next sign-in, before anything else.",
    neverSignedIn: "never",
    currentPassword: "Your current password",
    currentPasswordHint: "Confirms that you are the one making this change.",
    cancel: "Cancel",
    create: {
      title: "Create an account",
      note: "The new operator must change this password at their first sign-in. Give it to them through a safe channel.",
      submit: "Create the account",
      done: "Account {username} created.",
    },
    reset: {
      open: "Reset password",
      openLabel: "Reset the password of {username}",
      title: "New password for {username}",
      description:
        "They must change it at their next sign-in. Their open sessions are closed at once.",
      submit: "Reset the password",
      done: "The password of {username} is reset. They must change it at their next sign-in.",
    },
    disable: {
      open: "Disable",
      openLabel: "Disable {username}",
      title: "Disable {username}?",
      description:
        "They can no longer sign in, and their open sessions are closed at once. You can enable the account again later.",
      submit: "Disable the account",
      done: "{username} is disabled.",
    },
    enable: {
      open: "Enable",
      openLabel: "Enable {username}",
      title: "Enable {username}",
      description: "They can sign in again with their password.",
      submit: "Enable the account",
      done: "{username} is enabled.",
    },
    own: {
      title: "Change my password",
      intro:
        "Your other sessions are closed when the password changes; this one stays open.",
      submit: "Change my password",
      done: "Your password is changed. Your other sessions are closed.",
    },
  },
  format: {
    noValue: "n/a",
    unknown: "unknown",
    noLimit: "no limit",
    quota: "{used} / {limit}",
    lessThan: "< {amount}",
    milliseconds: "{value} ms",
    seconds: "{value} s",
    minutes: "{value} min",
    minutesSeconds: "{minutes} min {seconds} s",
    hours: "{value} h",
    ago: "{duration} ago",
  },
  /** The time zone and time range of a screen (`components/local-time.tsx`). */
  time: {
    zone: "Times in {timeZone}",
    range: "From {start} to {end}",
  },
  period: {
    label: "Period",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
  },
  filters: {
    tenant: "Tenant",
    allTenants: "All tenants",
    status: "Status",
    allStatuses: "All statuses",
    alias: "Alias",
    allAliases: "All aliases",
    aliasSearch: "Alias filter",
    apply: "Apply",
  },
  autoRefresh: {
    updated: "Updated {age}",
    paused: "Auto-refresh paused",
    pausedHidden: "Auto-refresh paused while the tab is hidden",
    failed: "Update failed",
    pause: "Pause",
    resume: "Resume",
    pauseLabel: "Pause auto-refresh",
    resumeLabel: "Resume auto-refresh",
  },
  statCard: {
    definitionOf: "Definition of {label}",
  },
  /**
   * Exact definitions of the figures, shown in tooltips. They follow the admin
   * API (`app/admin_api/statistics.py` and `app/admin_api/request_status.py`).
   */
  definitions: {
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
    savedCost:
      "What the cache hits would have cost if a provider had answered.",
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
  },
  overview: {
    title: "Overview",
    titleForTenant: "Overview: {tenant}",
    groups: {
      traffic: "Traffic",
      speed: "Speed",
      cost: "Tokens and cost",
      cache: "Cache",
    },
    requests: "Requests",
    answered: { one: "{count} answered", other: "{count} answered" },
    errorRate: "Error rate",
    errorDetail: "{failed}. Not counted: {clientErrors}, {cancelled}.",
    failed: { one: "{count} failed", other: "{count} failed" },
    clientErrors: {
      one: "{count} client error",
      other: "{count} client errors",
    },
    cancelled: { one: "{count} cancelled", other: "{count} cancelled" },
    fallbackRate: "Fallback rate",
    latency: "Latency p50",
    p95: "p95: {value}",
    timeToFirstToken: "Time to first token p50",
    timeToFirstTokenDetail: "p95: {value} · streams only",
    cacheHitLatency: "Cache hit latency p50",
    tokens: "Tokens",
    cost: "Cost",
    unpriced: {
      one: "{count} request without a price, not included",
      other: "{count} requests without a price, not included",
    },
    cacheHitRate: "Cache hit rate",
    cacheHitDetail: "{hits} of {requests}",
    hits: { one: "{count} hit", other: "{count} hits" },
    cachedRequests: {
      one: "{count} cached request",
      other: "{count} cached requests",
    },
    savedTokens: "Saved tokens",
    savedCost: "Saved cost",
  },
  charts: {
    label: "Charts",
    title: "Over time",
    requestsTitle: "Requests and failed requests",
    requests: "Requests",
    failed: "Failed",
    costTitle: "Cost (USD)",
    cost: "Cost",
    cacheHitsTitle: "Cache hits",
    cacheHits: "Cache hits",
    hourNote: "One bar per hour, times in {timeZone}.",
    dayNote: "One bar per UTC day.",
    utcDay: "{day} (UTC day)",
  },
  tenants: {
    title: "Tenants",
    tenant: "Tenant",
    requests: "Requests",
    tokens: "Tokens",
    cost: "Cost",
    costWithUnpriced: "{cost} ({count} without a price)",
    errorRate: "Error rate",
    cacheHits: "Cache hits",
    savedCost: "Saved cost",
    quotaRefusals: "Quota refusals",
    empty: "No tenant yet. Create one with {command}.",
  },
  /** Why a target gets traffic or not (`lib/target-health.ts`). */
  targetHealth: {
    labels: {
      healthy: "Healthy",
      cooling_down: "Cooling down",
      breaker_open: "Breaker open",
      half_open: "Breaker half-open",
      quota_full: "Quota full",
      live_unknown: "Live state unavailable (Redis)",
      removed: "No longer configured",
    },
    definitions: {
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
    },
  },
  providers: {
    title: "Providers & models",
    empty: "No target is configured: add routes to {file}.",
    byStatus: "Targets by status",
    statusCount: "{status}: {count}",
    status: "Status",
    statistics: "Statistics of the period",
    calls: "Calls",
    successRate: "Success rate",
    latency: "Latency p50 / p95",
    failures: "Failures",
    rateLimited: "Rate limited (429)",
    timeouts: "Timeouts",
    unavailable: "Unavailable",
    misconfigured: "Misconfigured",
    interrupted: "Interrupted streams",
    cancelled: "Cancelled by the client",
    skipped: "Skipped",
    cooldown: "Cooldown",
    breakerOpen: "Breaker open",
    quotaFull: "Quota full",
    causedByRequest: "Caused by the request",
    invalidRequests: "Invalid requests",
    tooLarge: "Too large for the target",
    liveState: "Live state",
    now: "Now",
    removed:
      "This target is in no route any more: the gateway does not use it.",
    liveUnknown:
      "Live state unavailable (Redis): cooldown, breaker and used quotas cannot be read. Only the configured limits are shown.",
    breaker: "Circuit breaker",
    rpm: "Requests per minute",
    tpm: "Tokens per minute",
    rpd: "Requests per day",
    dailyReset: "Daily reset",
    cooldownNone: "None",
    cooldownActive: "Active",
    cooldownUntil: "Active until {time}",
    breakerOpenState: "Open",
    breakerOpenUntil: "Open until {time}",
    halfOpenTrialRunning: "Half-open, trial call running",
    halfOpenWaiting: "Half-open, waiting for a trial call",
    breakerClosed: "Closed",
  },
  /** The statuses of a request (`app/admin_api/request_status.py`). */
  requestStatus: {
    labels: {
      answered: "Answered",
      failed: "Failed",
      client_error: "Client error",
      cancelled: "Cancelled",
    },
    definitions: {
      answered: "The client got an answer, from a provider or from the cache.",
      failed:
        "No answer because of the gateway or the providers: every target failed or was skipped (503), the deadline passed (504), or a stream was interrupted after its first token.",
      client_error:
        "The request itself was refused: invalid request (4xx from the provider), tenant quota exceeded (429), or too large for every target (400).",
      cancelled: "The client left before the answer ended.",
    },
  },
  /** What the response cache did (`cache` of a request). */
  cache: {
    off: "off",
    hit: "hit",
    miss: "miss",
    bypass: "bypass",
    unavailable: "unavailable",
  },
  requests: {
    title: "Requests",
    olderPage: "Older requests: auto-refresh is off on this page.",
    empty: "No request matches these filters in the period.",
    columns: {
      time: "Time",
      tenant: "Tenant",
      alias: "Alias",
      status: "Status",
      http: "HTTP",
      answeredBy: "Answered by",
      attempts: "Attempts",
      stream: "Stream",
      latency: "Latency",
      cost: "Cost",
      cache: "Cache",
    },
    columnDefinitions: {
      status:
        "Answered, failed (gateway or providers), client error (request refused) or cancelled (the client left).",
      http: "HTTP status of the last target examined.",
      answeredBy: "Provider and model of the answer.",
      attempts: "Targets examined, skips included.",
      latency: "Sum of the durations of the attempts.",
      cache:
        "What the response cache did: hit, miss, bypass or unavailable. Off when the alias does not use it.",
    },
    detailsOf: "Details of request {id}",
    yes: "yes",
    no: "no",
    notAnswered: "not answered",
    pages: "Pages of requests",
    newest: "Newest requests",
    older: "Older requests",
  },
  requestDetail: {
    back: "← Back to the requests",
    title: "Request {id}",
    notFound: "No request with this id.",
    notFoundHint:
      "Check the id. Old requests may have been removed from the usage log by its retention.",
    summary: "Summary",
    received: "Received",
    tenant: "Tenant",
    alias: "Alias",
    status: "Status",
    httpStatus: "HTTP status",
    answeredBy: "Answered by",
    attempts: "Attempts",
    stream: "Stream",
    latency: "Latency",
    cost: "Cost",
    cache: "Cache",
    pathTitle: "Routing path",
    pathIntro: "Every target the gateway examined for this request, in order.",
  },
  routingPath: {
    label: "Routing path",
    step: "Step {number}",
    noTarget: "No target examined",
    degraded: "Degraded mode",
    degradedDefinition:
      "The gateway routed without Redis: no quota, cooldown or breaker checks.",
    httpStatus: "HTTP status",
    latency: "Latency",
    firstToken: "First token",
    tokens: "Tokens",
    promptTokens: "{tokens} prompt",
    completionTokens: "{tokens} completion",
    estimatedTokens: "{tokens} estimated",
    cost: "Cost",
    savedCost: "Saved cost",
    cache: "Cache",
    similarity: "Similarity",
    identical: "1 (identical request)",
  },
  /** The outcome of one step of a routing path (`lib/outcomes.ts`). */
  outcomes: {
    kinds: {
      success: "Success",
      error: "Error",
      skipped: "Skipped",
      client_error: "Client error",
    },
    labels: {
      success: "Answered",
      cache_hit: "Answered from the cache",
      rate_limited: "Rate limited (429)",
      unavailable: "Unavailable (5xx or network error)",
      timeout: "Timeout",
      misconfigured: "Misconfigured (401, 403 or 404)",
      interrupted: "Stream interrupted after its first token",
      skipped_cooldown: "Cooldown active",
      skipped_breaker: "Circuit breaker open",
      skipped_quota: "Quota full",
      invalid_request: "Invalid request (4xx)",
      cancelled: "Cancelled by the client",
      rejected_tenant_quota: "Tenant quota exceeded (429)",
      context_too_large_skipped: "Too large for this target",
      context_too_large_refused: "Context too large (refused by the provider)",
    },
  },
  keys: {
    title: "Keys",
    intro:
      "Manage the API keys and limits of tenants. Gateways see changes within 60 seconds.",
    createHeading: "Create a key",
    tenantsHeading: "Tenants",
    selectTenant: "Select a tenant to see its limits and keys.",
    noTenant: "No tenant yet: create a key to create the first one.",
    historyHeading: "History of admin actions",
    fields: {
      tenant: "Tenant",
      rpm: "Requests per minute",
      tokens_per_day: "Tokens per day",
      rpmOptional: "Requests per minute (optional)",
      tokensOptional: "Tokens per day (optional)",
      cacheAlias: "Alias (optional: every alias when empty)",
    },
    create: {
      submit: "Create key",
      hint: "A new tenant is created with its first key. Limits given become the tenant's own limits; limits left empty keep their value.",
    },
    newKey: {
      heading: "New key for tenant {tenant}",
      warning:
        "Copy this key now. It will never be shown again: the gateway stores only a hash of it. Leaving or refreshing this page loses it.",
      label: "New API key",
      copy: "Copy key",
      stored: "I have stored the key",
      copied: "Copied to the clipboard.",
      copyFailed:
        "Copying is not available in this browser. Select the key above and copy it by hand (Ctrl+C or Cmd+C).",
    },
    panel: {
      title: "Tenant {tenant}",
      limits: "Limits",
      keys: "Keys",
      cache: "Cache",
    },
    limits: {
      limit: "Limit",
      own: "Own",
      applied: "Applied",
      tokensPerUtcDay: "Tokens per day (UTC day)",
      default: "default",
      noLimit: "no limit",
      now: "now: {value}",
      nowNoLimit: "now: no limit",
      hint: "Give at least one. A field left empty keeps its value. Gateways apply new limits within 60 seconds.",
      saved: "Limits saved.",
      submit: "Save limits",
    },
    table: {
      noKey: "This tenant has no key.",
      key: "Key",
      created: "Created",
      lastUsed: "Last used",
      status: "Status",
      actions: "Actions",
      never: "never",
      revoked: "Revoked {time}",
      active: "Active",
    },
    revoke: {
      open: "Revoke",
      openLabel: "Revoke key {prefix}",
      title: "Revoke key {prefix}?",
      description:
        "Applications using it are refused within 60 seconds. This cannot be undone.",
      confirm: "Revoke key",
      cancel: "Cancel",
    },
    cache: {
      submit: "Clear cache",
      removed: {
        one: "Removed {count} cached answer ({scope}).",
        other: "Removed {count} cached answers ({scope}).",
      },
      everyAlias: "every alias",
      oneAlias: "alias {alias}",
    },
    history: {
      empty: "No admin action yet.",
      time: "Time",
      actor: "Actor",
      action: "Action",
      target: "Target",
      details: "Details",
      loading: "Loading...",
      loadMore: "Load more",
      everyTenant: "every tenant",
      key: "key {id}",
      everyAlias: "every alias",
      /** The admin actions (`Action` of the admin API). */
      actions: {
        "create-key": "Create key",
        "revoke-key": "Revoke key",
        "set-limits": "Set limits",
        "clear-cache": "Clear cache",
        "purge-usage-log": "Purge usage log",
        "create-operator": "Create operator",
        "recover-operator": "Recover operator",
        "reset-password": "Reset password",
        "disable-operator": "Disable operator",
        "enable-operator": "Enable operator",
        "change-own-password": "Change own password",
        "create-admin-key": "Create admin key",
        "revoke-admin-key": "Revoke admin key",
      },
      /** The names of the details of an action; others show their raw name. */
      detailNames: {
        key_id: "key id",
        prefix: "prefix",
        tenant: "tenant",
        alias: "alias",
        rpm: "rpm",
        tokens_per_day: "tokens per day",
        removed: "removed",
        older_than_days: "older than days",
        deleted: "deleted",
        cutoff: "cutoff",
      },
    },
    /** Checks of the forms of the Keys screen (`lib/key-forms.ts`). */
    problems: {
      missingTenantName: "Enter the name of a tenant.",
      noTenantSelected: "No tenant is selected.",
      noLimitGiven:
        "Give at least one limit: requests per minute or tokens per day.",
      notWholeNumber: "{field} must be a whole number greater than 0.",
      tooLarge: "{field} is too large.",
      missingKeyId: "This key cannot be revoked: its id is missing.",
      noMoreActions: "No more actions to load.",
    },
    errors: {
      refusedValues: "The admin API refused the values.",
      httpError: "The admin API returned an error (HTTP {status}).",
    },
  },
} as const satisfies MessageTree;

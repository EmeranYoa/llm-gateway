# LLM Gateway admin dashboard

A Next.js (App Router) dashboard for the operator of the gateway. It reads
everything from the admin API (`app/admin_api/`) and never talks to PostgreSQL or
Redis itself.

## How sign-in works

- **First account** (`/setup`): while no operator account exists, the sign-in
  page opens the setup screen. It asks for the one-time setup token printed in
  the admin API logs (`docker compose logs admin-api`), a username and a
  password typed twice (at least 12 characters).
- **Sign-in** (`/login`): username and password. A server action sends them to
  `POST {ADMIN_API_URL}/admin/v1/sessions` and stores the session token it gets
  back in an encrypted session cookie (iron-session): `HttpOnly`, `Secure`,
  `SameSite=Strict`, 8 hours. Errors are translated from their code (wrong
  credentials, too many attempts with the wait time of `Retry-After`, admin API
  unavailable or unreachable).
- Pages call the admin API from the Next.js server (`src/api/client.ts`), with the
  token read from the session. The browser never receives a password or a token:
  it only holds the encrypted cookie, which JavaScript cannot read. Forms post
  through server actions only, never in a URL.
- `src/proxy.ts` sends visitors without a session to `/login`. When the admin API
  answers 401 (session expired, signed out, account disabled), the session is
  ended and the operator signs in again.
- **Forced password change** (`/change-password`): the protected layout reads
  the account once per request (`GET /admin/v1/me`, `lib/account.ts`). While
  `must_change_password` is set, every screen sends there; a 403
  `password_change_required` from any call does the same.
- **Sign-out** calls `DELETE /admin/v1/sessions/current` (a failure is
  ignored), then destroys the cookie.
- **Recovery** (`/recovery`): when the admin API runs with
  `OPERATOR_RECOVERY=true`, the sign-in page links to this screen: recovery
  token (from the admin API logs), username and new password. The operator then
  signs in with it and must change it. While recovery is on, a banner on every
  page asks to remove `OPERATOR_RECOVERY` and restart the admin API.
- Server actions only run when the `Origin` of the request matches the host of the
  dashboard (Next.js check, `allowedOrigins` is empty in `next.config.ts`). Behind
  a reverse proxy, forward `X-Forwarded-Host`, or add the public host there.

## Screens

- **Overview** (`/`): key figures of a period (requests, error rate, fallback rate,
  latency, time to first token, cost, cache savings) and charts per hour (24h) or
  per UTC day (7d, 30d). Each figure has a tooltip with its exact definition.
- **Tenants** (`/tenants`): one row per tenant. A row opens the overview of that
  tenant for the same period.
- **Providers & models** (`/providers`): one card per target (provider/model).
  Status badges say why traffic goes there or elsewhere right now (healthy,
  cooling down, breaker open or half-open, quota full, live state unavailable,
  no longer configured). Each card has the statistics of the period (calls,
  success rate, latency, failures and skips by reason) and the live state from
  Redis (cooldown, circuit breaker, RPM, TPM and RPD used against their limits).
- **Requests** (`/requests`): the requests of the period, newest first, 50 per
  page, filtered by tenant, alias and status. "Older requests" opens the next
  page. A row opens the **request detail** (`/requests/<id>`): its summary and
  its routing path, one step per target examined, with outcome, status code,
  latency, tokens, cost and cache.
- **Operators** (`/operators`): the operator accounts (you, enabled or
  disabled, must change password, last sign-in), and forms to create an
  account, reset another operator's password, disable or enable an account, and
  change your own password. Each form asks for your current password again.
  No action is offered on your own account except the password change, and
  disable is hidden for the last enabled account. This screen does not refresh
  by itself; each action reloads it.

Filters live in the URL (`/?period=7d&tenant=acme`), so a view can be bookmarked.
Changing a filter goes back to the first page of a list. Screens reload their
data every 10 s without a visible reload, except older pages of requests and the
request detail. Times come from the admin API in UTC and are shown in the
browser's time zone.

## Building blocks for screens

Reuse these when you add a screen:

| Piece                                                                        | What it does                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AutoRefresh` (`components/auto-refresh.tsx`)                                | Wraps the data of a server page. Props: `updatedAt` (ISO), `failed`, `dataKey` (the filters), `intervalMs` (default 10 s). Calls `router.refresh()`, shows "Updated N s ago" and a pause button, pauses while the tab is hidden, and keeps the last data with an "Update failed" badge when a refresh fails.                                        |
| `PeriodFilter`, `TenantFilter` (`components/filters.tsx`)                    | Write `?period=` and `?tenant=` to the URL, other params kept. Props: `value` (from the server page), and `tenants` (names) for `TenantFilter`. Parse the params with `parsePeriod` / `parseTenant` (`lib/period.ts`).                                                                                                                              |
| `RequestStatusFilter`, `AliasFilter` (`components/filters.tsx`)              | Write `?status=` and `?alias=`. Every filter removes `?cursor=`, so a list starts again from its first page. Parse the params of the Requests screen with `parseRequestFilters` (`lib/request-filters.ts`), which also builds the links (`requestsHref`, `requestHref`).                                                                            |
| `Badge` (`components/badge.tsx`)                                             | A short coloured label with a tooltip (`tone`, `title`). The text always says what the colour means.                                                                                                                                                                                                                                                |
| `StatCard` (`components/stat-card.tsx`)                                      | One figure. Props: `label`, `value` (formatted), `definition` (tooltip), optional `detail` and `warning`. Definitions live in `lib/definitions.ts`.                                                                                                                                                                                                 |
| `BarChartCard` (`components/bar-chart-card.tsx`)                             | A titled Recharts bar chart. Props: `title`, `data` (`label`, `tooltipLabel`, one value per series), `series` (`key`, `name`, `color`), `formatValue`, optional `formatTick`, `note` and `integer`. Animates on the first render only.                                                                                                              |
| `LocalDateTime`, `TimeZoneName`, `PeriodRange` (`components/local-time.tsx`) | Show UTC times of the admin API in the browser's time zone (`seconds` prop for short events), and name it.                                                                                                                                                                                                                                          |
| `lib/format.ts`                                                              | Every formatter takes the language first: `formatMoney(locale, usd)` (`null` → `unknown`), `formatMoneyTick`, `formatRate`, `formatDuration` (`null` → `n/a`), `formatCount`, `formatAge`, `formatDateTime` (optional seconds), `formatBucket`, `formatQuota` (`12 / 30`, `no limit`), `formatSimilarity`, `noValue`. `Intl` in `en-US` or `fr-FR`. |

A server page loads its data with `src/api/client.ts`, turns an `AdminApiError`
into a value with `.catch(keepApiError)`, and passes the result to `AutoRefresh`
(see `src/app/(protected)/tenants/page.tsx`).

## Languages

The dashboard speaks English and French. There is no i18n library:

- Texts live in typed dictionaries, `src/messages/en.ts` (the reference) and
  `src/messages/fr.ts`. `fr.ts` is typed from `en.ts`: a missing or extra key
  fails `bun run typecheck`. A message can have `{placeholders}` and plural
  forms (`{ one, other }`, chosen with `Intl.PluralRules`).
- `t(key, values)` reads a message by its dotted key (`t("nav.overview")`).
  Keys and placeholders are checked by the compiler. Server pages call
  `const { locale, t } = await getI18n()` (`lib/i18n/server.ts`) and pass
  `locale` to their components; client components call `useTranslator()` and
  `useLocale()` (`lib/i18n/client.tsx`).
- The language is, in order: the language saved in the signed-in operator's
  account, the `lang` cookie written by the language selector (one year), the
  browser's `Accept-Language` header, English (`resolveLocale` in
  `lib/i18n/locale.ts`). When signed in, the selector saves the choice in the
  account (`PUT /admin/v1/me/language`) and in the cookie, so the sign-in page
  keeps it after sign-out; signed out, it only writes the cookie.
- Errors of the admin API are translated from their `code`
  (`lib/i18n/api-errors.ts`); an unknown code shows a generic message and the
  English detail of the admin API.
- French texts follow French typography: a no-break space (written `\u00a0`) before
  `:`, `?`, `!`, `%` and units.

## Environment variables

| Variable                   | Required | Description                                                                                                |
| -------------------------- | -------- | ---------------------------------------------------------------------------------------------------------- |
| `ADMIN_API_URL`            | yes      | Address of the admin API, e.g. `http://admin-api:8001` in Docker Compose, `http://localhost:8001` locally. |
| `DASHBOARD_SESSION_SECRET` | yes      | Encrypts the session cookie. At least 32 characters: `openssl rand -base64 32`.                            |

The dashboard refuses to start when one of them is missing or invalid. There is
no default in the code, so it can never talk to the wrong admin API by accident.

## Run it locally

You need [bun](https://bun.sh) (packages and scripts) and Node.js 24 (Next.js
runs on Node.js).

```bash
# 1. Start the admin API on port 8001 (from the repository root).
uv run uvicorn app.admin_api.main:create_admin_app --factory --port 8001

# 2. Configure and start the dashboard (from dashboard/).
cat > .env.local <<EOF
ADMIN_API_URL=http://localhost:8001
DASHBOARD_SESSION_SECRET=$(openssl rand -base64 32)
EOF
bun install
bun run dev
```

Open http://localhost:3000. Browsers accept the `Secure` cookie on
`http://localhost`; anywhere else, serve the dashboard over HTTPS.

With Docker Compose, set `DASHBOARD_SESSION_SECRET` in the root `.env` and run
`docker compose up`: the dashboard is on http://localhost:3000.

## Scripts

| Script                   | What it does                                                     |
| ------------------------ | ---------------------------------------------------------------- |
| `bun run dev`            | Development server with hot reload.                              |
| `bun run build`          | Production build (`.next/standalone`, used by the Docker image). |
| `bun run lint`           | ESLint.                                                          |
| `bun run format`         | Format the code with Prettier (`format:check` only checks).      |
| `bun run typecheck`      | Generate the route types, then `tsc --noEmit`.                   |
| `bun run test`           | Vitest and Testing Library (no browser needed).                  |
| `bun run export:openapi` | Export the admin API schema to `openapi.json` (needs `uv`).      |
| `bun run generate:api`   | Generate `src/api/schema.ts` from `openapi.json`.                |

After changing the admin API, run `bun run export:openapi` then
`bun run generate:api`, and commit both files. CI fails when they are out of date.

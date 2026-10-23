# LLM Gateway admin dashboard

A Next.js (App Router) dashboard for the operator of the gateway. It reads
everything from the admin API (`app/admin_api/`) and never talks to PostgreSQL or
Redis itself.

## How sign-in works

- The operator signs in on `/login` with an admin key (`gwa_...`, created with
  `python -m app.admin create-admin-key --name <you>`).
- A server action checks the key with `GET {ADMIN_API_URL}/admin/v1/me`. When the
  admin API accepts it, the key is stored in an encrypted session cookie
  (iron-session): `HttpOnly`, `Secure`, `SameSite=Strict`, 8 hours.
- Pages call the admin API from the Next.js server (`src/api/client.ts`), with the
  key read from the session. The browser never receives the key: it only holds
  the encrypted cookie, which JavaScript cannot read.
- `src/proxy.ts` sends visitors without a session to `/login`. When the admin API
  answers 401 (revoked key), the session is ended and the operator signs in again.
- Server actions only run when the `Origin` of the request matches the host of the
  dashboard (Next.js check, `allowedOrigins` is empty in `next.config.ts`). Behind
  a reverse proxy, forward `X-Forwarded-Host`, or add the public host there.

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

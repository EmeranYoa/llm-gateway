# Build stage: bun installs the packages and runs the build. Next.js itself
# builds on Node.js, the runtime used in production.
FROM node:24.22.1-slim AS build

COPY --from=oven/bun:1.4.4-slim /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Install packages first so this layer is cached when only the code changes.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .
RUN bun run build

# Run stage: only the standalone server and the static files, on Node.js LTS.
FROM node:24.22.1-slim

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static

# The `node` user comes with the official image: the server does not run as root.
USER node

EXPOSE 3000
CMD ["node", "server.js"]

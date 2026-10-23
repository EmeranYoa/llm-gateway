import "server-only";

/**
 * Settings of the dashboard, read from environment variables.
 *
 * Both are required and have no default in the code: a dashboard that silently
 * talked to the wrong admin API, or signed its cookies with a weak secret, would
 * be worse than one that refuses to start. Docker Compose sets them.
 */

/** iron-session needs at least 32 characters to derive a strong encryption key. */
export const MIN_SESSION_SECRET_LENGTH = 32;

export type DashboardConfig = {
  /** Base URL of the admin API, without a trailing slash. */
  adminApiUrl: string;
  /** Secret that encrypts the session cookie. */
  sessionSecret: string;
};

type Env = Record<string, string | undefined>;

/** A missing or invalid setting. The message says how to fix it. */
export class DashboardConfigError extends Error {
  override name = "DashboardConfigError";
}

export function readDashboardConfig(env: Env = process.env): DashboardConfig {
  return {
    adminApiUrl: checkAdminApiUrl(env.ADMIN_API_URL),
    sessionSecret: checkSessionSecret(env.DASHBOARD_SESSION_SECRET),
  };
}

export function checkSessionSecret(secret: string | undefined): string {
  if (!secret) {
    throw new DashboardConfigError(
      "DASHBOARD_SESSION_SECRET is missing. Generate one with `openssl rand -base64 32`.",
    );
  }
  if (secret.length < MIN_SESSION_SECRET_LENGTH) {
    throw new DashboardConfigError(
      `DASHBOARD_SESSION_SECRET must have at least ${MIN_SESSION_SECRET_LENGTH} characters. ` +
        "Generate one with `openssl rand -base64 32`.",
    );
  }
  return secret;
}

function checkAdminApiUrl(value: string | undefined): string {
  if (!value) {
    throw new DashboardConfigError(
      "ADMIN_API_URL is missing. Set it to the address of the admin API, " +
        "for example http://admin-api:8001 in Docker Compose.",
    );
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new DashboardConfigError(
      `ADMIN_API_URL is not a valid URL: ${value}`,
    );
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new DashboardConfigError(
      `ADMIN_API_URL must start with http:// or https://, got: ${value}`,
    );
  }
  return value.replace(/\/+$/, "");
}

import "server-only";

import type { SessionOptions } from "iron-session";

import { checkSessionSecret } from "./config";

/**
 * How the session cookie is built. The cookie holds the session token of the
 * admin API, encrypted and signed by iron-session with DASHBOARD_SESSION_SECRET.
 */

export const SESSION_COOKIE_NAME = "gateway_dashboard_session";

/** An operator signs in again after 8 hours, like the session of the admin API. */
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;

/** What the session cookie holds. Only the Next.js server can read it. */
export type SessionData = {
  /** The session token returned by the admin API at sign-in or setup. */
  token: string;
};

/** Build the iron-session options. Throws when the secret is missing or too short. */
export function buildSessionOptions(
  secret: string | undefined,
): SessionOptions {
  return {
    password: checkSessionSecret(secret),
    cookieName: SESSION_COOKIE_NAME,
    // The encrypted content expires after 8 hours, even if a browser keeps the cookie.
    ttl: SESSION_MAX_AGE_SECONDS,
    cookieOptions: {
      httpOnly: true, // never readable from JavaScript in the browser
      secure: true, // sent over HTTPS only (browsers also accept http://localhost)
      sameSite: "strict", // never sent with a request started by another site
      path: "/",
      maxAge: SESSION_MAX_AGE_SECONDS,
    },
    onUnsealError: (reason) => {
      if (reason !== "expired") {
        console.warn(`Session cookie rejected (${reason}): signed out.`);
      }
    },
  };
}

/** The session options of this process, from DASHBOARD_SESSION_SECRET. */
export function sessionOptions(): SessionOptions {
  return buildSessionOptions(process.env.DASHBOARD_SESSION_SECRET);
}

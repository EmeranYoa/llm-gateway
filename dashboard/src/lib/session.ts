import "server-only";

import { getIronSession, type IronSession } from "iron-session";
import { cookies } from "next/headers";

import { type SessionData, sessionOptions } from "./session-options";

export type Session = IronSession<SessionData>;

/**
 * The session of the current request.
 *
 * Reading works everywhere on the server. `save()` and `destroy()` change the
 * cookie, so Next.js allows them only in server actions and route handlers.
 */
export async function getSession(): Promise<Session> {
  return getIronSession<SessionData>(await cookies(), sessionOptions());
}

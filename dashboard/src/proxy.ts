import { getIronSession, nextProxyCookies } from "iron-session";
import { type NextRequest, NextResponse } from "next/server";

import { type SessionData, sessionOptions } from "@/lib/session-options";

/**
 * Runs before every protected page: a visitor without a valid session cookie is
 * sent to the sign-in page. A session ended on the admin API still has a valid
 * cookie: the API client catches it on the first call to the admin API (401).
 */
export async function proxy(request: NextRequest): Promise<NextResponse> {
  const response = NextResponse.next();
  const session = await getIronSession<SessionData>(
    nextProxyCookies(request, response),
    sessionOptions(),
  );
  if (!session.token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return response;
}

export const config = {
  // Every page except the pages used without a session (sign-in, setup of the
  // first account, account recovery), the route that ends a session, and
  // static files.
  matcher: [
    "/((?!login|setup|recovery|session-expired|_next/static|_next/image|favicon.ico).*)",
  ],
};

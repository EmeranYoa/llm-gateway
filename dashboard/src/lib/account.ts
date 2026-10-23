import "server-only";

import { cache } from "react";

import {
  AdminApiError,
  callWithToken,
  CHANGE_PASSWORD_PATH,
  type Me,
  SESSION_EXPIRED_PATH,
} from "@/api/client";

import { getSession } from "./session";

/**
 * The account of the operator signed in on the current request, read once per
 * request with `GET /admin/v1/me`.
 *
 * Nothing redirects here: the root layout reads the account for its language
 * on every page (the sign-in page too), and the protected layout decides what
 * to do with each state (see `accountRedirect`).
 */
export type AccountState =
  | { status: "signed-out" }
  /** The admin API refused the session token (401): the session has ended. */
  | { status: "expired" }
  | { status: "signed-in"; me: Me }
  /** The admin API could not answer (unreachable, database down...). */
  | { status: "unavailable"; error: AdminApiError };

export const loadAccount = cache(async (): Promise<AccountState> => {
  const { token } = await getSession();
  if (!token) {
    return { status: "signed-out" };
  }
  try {
    return {
      status: "signed-in",
      me: await callWithToken<Me>("/admin/v1/me", token),
    };
  } catch (error) {
    if (!(error instanceof AdminApiError)) {
      throw error;
    }
    if (error.status === 401) {
      return { status: "expired" };
    }
    return { status: "unavailable", error };
  }
});

/**
 * Where a protected page must send the operator, or null to show the page:
 *
 * - no session → the sign-in page (the proxy normally did it already);
 * - session refused by the admin API → `/session-expired`, which ends it;
 * - password to change → `/change-password`.
 *
 * When the admin API is unavailable the page is shown: its own calls fail and
 * show the error.
 */
export function accountRedirect(account: AccountState): string | null {
  switch (account.status) {
    case "signed-out":
      return "/login";
    case "expired":
      return SESSION_EXPIRED_PATH;
    case "signed-in":
      return account.me.must_change_password ? CHANGE_PASSWORD_PATH : null;
    case "unavailable":
      return null;
  }
}

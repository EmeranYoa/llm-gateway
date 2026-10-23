"use server";

import { redirect } from "next/navigation";

import { AdminApiError, checkAdminKey } from "@/api/client";
import { getSession } from "@/lib/session";

/**
 * Sign-in and sign-out, as server actions.
 *
 * The admin key is posted once by the sign-in form, checked against the admin
 * API, then kept only in the encrypted session cookie. No action returns it.
 */

export type LoginState = {
  /** Message shown on the sign-in form, or null when there is nothing to say. */
  error: string | null;
};

const ADMIN_KEY_PREFIX = "gwa_";

export async function login(
  _previous: LoginState,
  form: FormData,
): Promise<LoginState> {
  const adminKey = String(form.get("adminKey") ?? "").trim();
  if (!adminKey.startsWith(ADMIN_KEY_PREFIX)) {
    return { error: "Enter an admin key: it starts with gwa_." };
  }

  let operator;
  try {
    operator = await checkAdminKey(adminKey);
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { error: `The key cannot be checked right now. ${error.message}` };
    }
    throw error;
  }
  if (operator === null) {
    return { error: "This admin key is not valid, or it has been revoked." };
  }

  const session = await getSession();
  session.adminKey = adminKey;
  await session.save();
  redirect("/");
}

export async function logout(): Promise<void> {
  const session = await getSession();
  session.destroy();
  redirect("/login");
}

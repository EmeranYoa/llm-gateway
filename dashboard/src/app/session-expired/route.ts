import { redirect } from "next/navigation";

import { getSession } from "@/lib/session";

/**
 * End a session whose admin key the admin API refused (revoked key).
 *
 * The API client sends the operator here on a 401: a page being rendered is not
 * allowed to change cookies, a route handler is. Calling it from another site
 * does nothing, because the strict SameSite cookie is not sent with that request.
 */
export async function GET(): Promise<never> {
  const session = await getSession();
  session.destroy();
  redirect("/login?expired=1");
}

import { redirect } from "next/navigation";

import { NavBar } from "@/components/nav-bar";
import { accountRedirect, loadAccount } from "@/lib/account";
import { getLocale } from "@/lib/i18n/server";

/**
 * Layout of the pages that need a signed-in operator. `src/proxy.ts` sends
 * visitors without a session cookie to /login before these pages run.
 *
 * The account is read once per request (`GET /admin/v1/me`): an operator who
 * must change their password is sent to /change-password before any screen,
 * and a session refused by the admin API is ended. The API client does the
 * same on any later call refused with 403 `password_change_required` or 401.
 */
export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const target = accountRedirect(await loadAccount());
  if (target !== null) {
    redirect(target);
  }
  const locale = await getLocale();
  return (
    <>
      <NavBar locale={locale} />
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </>
  );
}

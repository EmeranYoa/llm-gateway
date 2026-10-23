import { NavBar } from "@/components/nav-bar";
import { getLocale } from "@/lib/i18n/server";

/**
 * Layout of the pages that need a signed-in operator. `src/proxy.ts` sends
 * visitors without a session to /login before these pages run.
 */
export default async function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  return (
    <>
      <NavBar locale={locale} />
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </>
  );
}

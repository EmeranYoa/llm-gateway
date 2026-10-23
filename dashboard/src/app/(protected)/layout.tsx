import { NavBar } from "@/components/nav-bar";

/**
 * Layout of the pages that need a signed-in operator. `src/proxy.ts` sends
 * visitors without a session to /login before these pages run.
 */
export default function ProtectedLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <NavBar />
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </>
  );
}

import Link from "next/link";

import { logout } from "@/lib/auth-actions";

/** The screens of the dashboard. Pages not built yet show a placeholder. */
const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/tenants", label: "Tenants" },
  { href: "/providers", label: "Providers" },
  { href: "/requests", label: "Requests" },
  { href: "/keys", label: "Keys" },
] as const;

export function NavBar() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <span className="font-semibold">LLM Gateway admin</span>
        <ul className="flex flex-wrap gap-4 text-sm">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-slate-600 hover:text-slate-900"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
        <form action={logout} className="ml-auto">
          <button
            type="submit"
            className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
          >
            Sign out
          </button>
        </form>
      </nav>
    </header>
  );
}

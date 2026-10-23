import Link from "next/link";

import { logout } from "@/lib/auth-actions";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

import { LanguageSelector } from "./language-selector";

/** The screens of the dashboard, with the key of their name in the dictionaries. */
const LINKS = [
  { href: "/", label: "nav.overview" },
  { href: "/tenants", label: "nav.tenants" },
  { href: "/providers", label: "nav.providers" },
  { href: "/requests", label: "nav.requests" },
  { href: "/keys", label: "nav.keys" },
] as const;

export function NavBar({ locale }: { locale: Locale }) {
  const t = getTranslator(locale);
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav
        aria-label={t("nav.label")}
        className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3"
      >
        <span className="font-semibold">{t("app.title")}</span>
        <ul className="flex flex-wrap gap-4 text-sm">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-slate-600 hover:text-slate-900"
              >
                {t(link.label)}
              </Link>
            </li>
          ))}
        </ul>
        <div className="ml-auto flex items-center gap-4">
          <LanguageSelector />
          <form action={logout}>
            <button
              type="submit"
              className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
            >
              {t("nav.signOut")}
            </button>
          </form>
        </div>
      </nav>
    </header>
  );
}

import Link from "next/link";

import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

/** The tenants, as links that select one in the URL (`/keys?tenant=name`). */
export function TenantList({
  names,
  selected,
  locale,
}: {
  names: string[];
  selected: string | null;
  locale: Locale;
}) {
  if (names.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        {getTranslator(locale)("keys.noTenant")}
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {names.map((name) => {
        const current = name === selected;
        return (
          <li key={name}>
            <Link
              href={{ pathname: "/keys", query: { tenant: name } }}
              aria-current={current ? "page" : undefined}
              className={
                current
                  ? "block rounded bg-slate-900 px-3 py-1.5 text-white"
                  : "block rounded px-3 py-1.5 text-slate-700 hover:bg-slate-100"
              }
            >
              {name}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

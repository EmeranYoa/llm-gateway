"use client";

import { useRouter } from "next/navigation";

import { useLocale, useTranslator } from "@/lib/i18n/client";
import {
  isLocale,
  LOCALE_NAMES,
  LOCALES,
  localeCookie,
} from "@/lib/i18n/locale";

/**
 * The language of the dashboard, in the nav bar. The choice is kept in the
 * `lang` cookie (one year), which wins over the browser's `Accept-Language`;
 * the page then reloads its server components in the new language.
 */
export function LanguageSelector() {
  const locale = useLocale();
  const t = useTranslator();
  const router = useRouter();

  function choose(value: string) {
    if (!isLocale(value)) {
      return;
    }
    document.cookie = localeCookie(
      value,
      window.location.protocol === "https:",
    );
    router.refresh();
  }

  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      <span>{t("language.label")}</span>
      <select
        // A new language from the server resets the shown value.
        key={locale}
        defaultValue={locale}
        onChange={(event) => choose(event.target.value)}
        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:ring-2 focus:ring-sky-600 focus:outline-none"
      >
        {LOCALES.map((option) => (
          <option key={option} value={option} lang={option}>
            {LOCALE_NAMES[option]}
          </option>
        ))}
      </select>
    </label>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { useLocale, useTranslator } from "@/lib/i18n/client";
import {
  isLocale,
  LOCALE_NAMES,
  LOCALES,
  localeCookie,
} from "@/lib/i18n/locale";

type LanguageSelectorProps = {
  /**
   * Saves the language in the signed-in operator's account (the
   * `saveLanguageAction` server action). Left out when nobody is signed in:
   * the choice then only goes into the cookie.
   */
  save?: (language: string) => Promise<{ saved: boolean }>;
};

/**
 * The language of the dashboard. The choice is kept in the `lang` cookie (one
 * year), which wins over the browser's `Accept-Language`, and, when signed in,
 * in the account, which wins over the cookie. The page then reloads its server
 * components in the new language.
 */
export function LanguageSelector({ save }: LanguageSelectorProps) {
  const locale = useLocale();
  const t = useTranslator();
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const [pending, startTransition] = useTransition();

  function choose(value: string) {
    if (!isLocale(value)) {
      return;
    }
    document.cookie = localeCookie(
      value,
      window.location.protocol === "https:",
    );
    if (save === undefined) {
      router.refresh();
      return;
    }
    startTransition(async () => {
      // Saved first: the account language wins over the cookie on the next render.
      const { saved } = await save(value);
      setFailed(!saved);
      router.refresh();
    });
  }

  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <span>{t("language.label")}</span>
        <select
          // A new language from the server resets the shown value.
          key={locale}
          defaultValue={locale}
          disabled={pending}
          onChange={(event) => choose(event.target.value)}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:ring-2 focus:ring-sky-600 focus:outline-none disabled:opacity-60"
        >
          {LOCALES.map((option) => (
            <option key={option} value={option} lang={option}>
              {LOCALE_NAMES[option]}
            </option>
          ))}
        </select>
      </label>
      {failed && (
        <p role="alert" className="text-xs text-red-700">
          {t("language.saveFailed")}
        </p>
      )}
    </div>
  );
}

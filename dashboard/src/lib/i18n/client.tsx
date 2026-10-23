"use client";

import { createContext, useContext } from "react";

import { DEFAULT_LOCALE, type Locale } from "./locale";
import { getTranslator, type Translator } from "./translator";

/**
 * The language of the page for client components. The root layout reads it on
 * the server and provides it here; without a provider (tests), it is English.
 */
const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

export function LocaleProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  return <LocaleContext value={locale}>{children}</LocaleContext>;
}

/** The language of the page, for the formatters of `lib/format.ts`. */
export function useLocale(): Locale {
  return useContext(LocaleContext);
}

/** `t()` in the language of the page: `const t = useTranslator();`. */
export function useTranslator(): Translator {
  return getTranslator(useLocale());
}

import "server-only";

import { cookies, headers } from "next/headers";
import { cache } from "react";

import { LOCALE_COOKIE, type Locale, resolveLocale } from "./locale";
import { getTranslator, type Translator } from "./translator";

/**
 * The language of the current request: the `lang` cookie, else the
 * `Accept-Language` header, else English (see `resolveLocale`). Read once per
 * request.
 */
export const getLocale = cache(async (): Promise<Locale> => {
  const [cookieStore, headerList] = await Promise.all([cookies(), headers()]);
  return resolveLocale(
    cookieStore.get(LOCALE_COOKIE)?.value,
    headerList.get("accept-language"),
  );
});

/**
 * The language of the current request and its translator, for server pages:
 *
 *   const { locale, t } = await getI18n();
 *
 * Pass `locale` to the components and formatters the page renders.
 */
export async function getI18n(): Promise<{ locale: Locale; t: Translator }> {
  const locale = await getLocale();
  return { locale, t: getTranslator(locale) };
}

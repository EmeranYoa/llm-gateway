import "server-only";

import { cookies, headers } from "next/headers";
import { cache } from "react";

import { loadAccount } from "@/lib/account";
import { SESSION_COOKIE_NAME } from "@/lib/session-options";

import { LOCALE_COOKIE, type Locale, resolveLocale } from "./locale";
import { getTranslator, type Translator } from "./translator";

/**
 * The language of the current request: the language saved in the signed-in
 * operator's account, else the `lang` cookie, else the `Accept-Language`
 * header, else English (see `resolveLocale`). Read once per request.
 */
export const getLocale = cache(async (): Promise<Locale> => {
  const [cookieStore, headerList] = await Promise.all([cookies(), headers()]);
  return resolveLocale(
    cookieStore.get(LOCALE_COOKIE)?.value,
    headerList.get("accept-language"),
    await accountLanguage(cookieStore.get(SESSION_COOKIE_NAME) !== undefined),
  );
});

/**
 * The language saved in the account, or null. Without a session cookie there
 * is no account to ask, so a visitor who is not signed in never waits for the
 * admin API. When the admin API cannot answer, the other choices decide.
 */
async function accountLanguage(hasSession: boolean): Promise<string | null> {
  if (!hasSession) {
    return null;
  }
  const account = await loadAccount();
  return account.status === "signed-in" ? account.me.language : null;
}

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

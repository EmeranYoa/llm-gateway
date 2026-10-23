/**
 * The languages of the dashboard, and how the language of a visitor is chosen.
 *
 * Pure functions only: usable on the server, in the browser and in tests.
 */

export const LOCALES = ["en", "fr"] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

/** The `Intl` locale of each language, for numbers, money and dates. */
export const INTL_LOCALES: Record<Locale, string> = {
  en: "en-US",
  fr: "fr-FR",
};

/** Each language named in itself, so an operator always finds their own. */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  fr: "Français",
};

/** The cookie that keeps the language chosen in the nav bar. */
export const LOCALE_COOKIE = "lang";

const ONE_YEAR_IN_SECONDS = 365 * 24 * 60 * 60;

export function isLocale(value: unknown): value is Locale {
  return LOCALES.some((locale) => locale === value);
}

/**
 * The language of a request, from the most to the least explicit choice:
 *
 * 1. the language saved in the operator's account (`accountLanguage`, not
 *    passed yet: the account API does not exist);
 * 2. the `lang` cookie written by the language selector;
 * 3. the browser's `Accept-Language` header;
 * 4. English.
 *
 * Unsupported or invalid values are skipped.
 */
export function resolveLocale(
  cookie: string | null | undefined,
  acceptLanguage: string | null | undefined,
  accountLanguage?: string | null,
): Locale {
  if (isLocale(accountLanguage)) {
    return accountLanguage;
  }
  if (isLocale(cookie)) {
    return cookie;
  }
  return localeFromAcceptLanguage(acceptLanguage ?? "") ?? DEFAULT_LOCALE;
}

/**
 * The supported language the browser prefers, from an `Accept-Language`
 * header such as `fr-CA,fr;q=0.9,en;q=0.8`, or null when none is supported.
 * Only the primary subtag counts: `fr-CA` gives `fr`.
 */
export function localeFromAcceptLanguage(header: string): Locale | null {
  const ranked = header
    .split(",")
    .map((part, position) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.find((param) => param.trim().startsWith("q="));
      const weight = q === undefined ? 1 : Number(q.trim().slice(2));
      const language = tag.trim().split("-")[0].toLowerCase();
      return { language, weight: Number.isNaN(weight) ? 0 : weight, position };
    })
    .filter((entry) => entry.weight > 0)
    // Highest weight first; equal weights keep the order of the header.
    .sort((a, b) => b.weight - a.weight || a.position - b.position);
  return ranked.map((entry) => entry.language).find(isLocale) ?? null;
}

/**
 * The `Set-Cookie`-style text that keeps a language for one year, readable by
 * the server on every request. Not `HttpOnly`: the language is no secret, and
 * the selector writes it from the browser. `Secure` on HTTPS.
 */
export function localeCookie(locale: Locale, secure: boolean): string {
  const attributes = [
    `${LOCALE_COOKIE}=${locale}`,
    "Path=/",
    `Max-Age=${ONE_YEAR_IN_SECONDS}`,
    "SameSite=Lax",
  ];
  if (secure) {
    attributes.push("Secure");
  }
  return attributes.join("; ");
}

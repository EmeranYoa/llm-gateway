/**
 * Formatting helpers shared by every screen.
 *
 * Every formatter takes the language of the page first (`Locale`, see
 * `lib/i18n`): numbers, money and dates follow `Intl` in `en-US` or `fr-FR`
 * (`1,250.5` or `1 250,5`), and words come from the dictionaries. The server
 * and the browser get the same language, so they produce the same text.
 *
 * Dates take an explicit time zone: the admin API returns UTC, and the screens
 * show the browser's time zone (see `useBrowserTimeZone`).
 */

import { INTL_LOCALES, LOCALES, type Locale } from "./i18n/locale";
import { getTranslator } from "./i18n/translator";
import type { Period } from "./period";

/** Amounts below this many dollars show as `< $0.000001`. */
const SMALLEST_USD = 0.000001;

function numberFormats(intlLocale: string) {
  const money = {
    style: "currency",
    currency: "USD",
    // `$` in every language: `$1.50`, `1,50 $` (not `1,50 $US`).
    currencyDisplay: "narrowSymbol",
  } as const;
  return {
    count: new Intl.NumberFormat(intlLocale),
    usd: new Intl.NumberFormat(intlLocale, {
      ...money,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
    /** Amounts below one cent keep up to 6 decimals, so they do not show as $0.00. */
    smallUsd: new Intl.NumberFormat(intlLocale, {
      ...money,
      minimumFractionDigits: 2,
      maximumFractionDigits: 6,
    }),
    usdTick: new Intl.NumberFormat(intlLocale, {
      ...money,
      maximumSignificantDigits: 3,
    }),
    percent: new Intl.NumberFormat(intlLocale, {
      style: "percent",
      maximumFractionDigits: 1,
    }),
    oneDecimal: new Intl.NumberFormat(intlLocale, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }),
    similarity: new Intl.NumberFormat(intlLocale, { maximumFractionDigits: 3 }),
  };
}

const FORMATS = Object.fromEntries(
  LOCALES.map((locale) => [locale, numberFormats(INTL_LOCALES[locale])]),
) as Record<Locale, ReturnType<typeof numberFormats>>;

/** Shown when a value is missing (nothing was measured): `n/a`, `n.d.`. */
export function noValue(locale: Locale): string {
  return getTranslator(locale)("format.noValue");
}

/** A whole number with thousands separators: `12,345`, `12 345`. */
export function formatCount(locale: Locale, value: number): string {
  return FORMATS[locale].count.format(value);
}

/**
 * A USD amount: `$1,234.50` (`1 234,50 $`), `$0.0012` below one cent.
 *
 * `null` or `undefined` means the price is not known, which is not the same as
 * free: it gives `unknown`, never `$0.00`.
 */
export function formatMoney(
  locale: Locale,
  usd: number | null | undefined,
): string {
  const formats = FORMATS[locale];
  if (usd === null || usd === undefined) {
    return getTranslator(locale)("format.unknown");
  }
  const size = Math.abs(usd);
  if (size === 0 || size >= 0.01) {
    return formats.usd.format(usd);
  }
  if (size < SMALLEST_USD) {
    return getTranslator(locale)("format.lessThan", {
      amount: formats.smallUsd.format(SMALLEST_USD),
    });
  }
  return formats.smallUsd.format(usd);
}

/**
 * A USD amount on a chart axis, with 3 significant digits: `$0.015`, `$1.25`.
 * Small amounts keep their decimals, so two ticks never show the same text.
 */
export function formatMoneyTick(locale: Locale, usd: number): string {
  return FORMATS[locale].usdTick.format(usd);
}

/** A share between 0 and 1 as a percentage with at most one decimal: `0.125` → `12.5%`. */
export function formatRate(locale: Locale, fraction: number): string {
  return FORMATS[locale].percent.format(fraction);
}

/**
 * A duration in milliseconds: `850 ms`, `2.1 s`, `1 min 5 s`.
 * `null` (nothing measured) gives `n/a`.
 */
export function formatDuration(
  locale: Locale,
  ms: number | null | undefined,
): string {
  const t = getTranslator(locale);
  if (ms === null || ms === undefined) {
    return t("format.noValue");
  }
  if (ms < 1000) {
    return t("format.milliseconds", { value: Math.round(ms) });
  }
  if (ms < 60_000) {
    const seconds = FORMATS[locale].oneDecimal.format(ms / 1000);
    return t("format.seconds", { value: seconds });
  }
  const seconds = Math.round(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0
    ? t("format.minutes", { value: minutes })
    : t("format.minutesSeconds", { minutes, seconds: rest });
}

/** How long ago something happened, from a number of seconds: `5 s ago`, `2 min ago`. */
export function formatAge(locale: Locale, seconds: number): string {
  const t = getTranslator(locale);
  const whole = Math.max(0, Math.floor(seconds));
  const duration =
    whole < 60
      ? t("format.seconds", { value: whole })
      : whole < 3600
        ? t("format.minutes", { value: Math.floor(whole / 60) })
        : t("format.hours", { value: Math.floor(whole / 3600) });
  return t("format.ago", { duration });
}

/**
 * A moment returned by the admin API (ISO 8601, UTC) in a given time zone:
 * `Oct 23, 2026, 14:05` (`23 oct. 2026, 14:05`), with the seconds on request.
 */
export function formatDateTime(
  locale: Locale,
  iso: string,
  timeZone: string,
  { seconds = false }: { seconds?: boolean } = {},
): string {
  return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
    timeZone,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
    hourCycle: "h23",
  }).format(new Date(iso));
}

/**
 * The label of one point of a time series (see `SeriesPoint.start`).
 *
 * A 24h period has one point per hour: its hour in the given time zone (`14:00`).
 * Longer periods have one point per UTC day: the day, always read in UTC
 * (`Oct 21`, `21 oct.`), because the bucket is a UTC day whatever the browser's
 * time zone.
 */
export function formatBucket(
  locale: Locale,
  iso: string,
  period: Period,
  timeZone: string,
): string {
  if (period === "24h") {
    return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date(iso));
  }
  return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
  }).format(new Date(iso));
}

/**
 * How much of a quota is used: `12 / 30`.
 * No limit gives `no limit`; an unknown use (Redis down) gives `unknown / 30`.
 */
export function formatQuota(
  locale: Locale,
  used: number | null,
  limit: number | null,
): string {
  const t = getTranslator(locale);
  if (limit === null) {
    return t("format.noLimit");
  }
  return t("format.quota", {
    used: used === null ? t("format.unknown") : formatCount(locale, used),
    limit: formatCount(locale, limit),
  });
}

/** A cosine similarity between 0 and 1, with up to 3 decimals: `0.973`, `1`. */
export function formatSimilarity(locale: Locale, value: number | null): string {
  if (value === null) {
    return noValue(locale);
  }
  return FORMATS[locale].similarity.format(value);
}

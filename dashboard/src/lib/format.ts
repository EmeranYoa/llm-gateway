/**
 * Formatting helpers shared by every screen.
 *
 * Everything is formatted in English (`en-US`), so the server and the browser
 * produce the same text. Dates take an explicit time zone: the admin API
 * returns UTC, and the screens show the browser's time zone (see
 * `useBrowserTimeZone`).
 */

import type { Period } from "./period";

const LOCALE = "en-US";

/** Shown when a duration or a percentile has no value (nothing was measured). */
export const NO_VALUE = "n/a";

const COUNT = new Intl.NumberFormat(LOCALE);
const USD = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
/** Amounts below one cent keep up to 6 decimals, so they do not show as $0.00. */
const SMALL_USD = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});
const SMALLEST_USD = 0.000001;
const PERCENT = new Intl.NumberFormat(LOCALE, {
  style: "percent",
  maximumFractionDigits: 1,
});

/** A whole number with thousands separators: `12,345`. */
export function formatCount(value: number): string {
  return COUNT.format(value);
}

/**
 * A USD amount: `$1,234.50`, `$0.0012` below one cent.
 *
 * `null` or `undefined` means the price is not known, which is not the same as
 * free: it gives `unknown`, never `$0.00`.
 */
export function formatMoney(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) {
    return "unknown";
  }
  const size = Math.abs(usd);
  if (size === 0 || size >= 0.01) {
    return USD.format(usd);
  }
  if (size < SMALLEST_USD) {
    return `< ${SMALL_USD.format(SMALLEST_USD)}`;
  }
  return SMALL_USD.format(usd);
}

const USD_TICK = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  maximumSignificantDigits: 3,
});

/**
 * A USD amount on a chart axis, with 3 significant digits: `$0.015`, `$1.25`.
 * Small amounts keep their decimals, so two ticks never show the same text.
 */
export function formatMoneyTick(usd: number): string {
  return usd === 0 ? "$0" : USD_TICK.format(usd);
}

/** A share between 0 and 1 as a percentage with at most one decimal: `0.125` → `12.5%`. */
export function formatRate(fraction: number): string {
  return PERCENT.format(fraction);
}

/**
 * A duration in milliseconds: `850 ms`, `2.1 s`, `1 min 5 s`.
 * `null` (nothing measured) gives `n/a`.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return NO_VALUE;
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(1)} s`;
  }
  const seconds = Math.round(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** How long ago something happened, from a number of seconds: `5 s ago`, `2 min ago`. */
export function formatAge(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) {
    return `${whole} s ago`;
  }
  if (whole < 3600) {
    return `${Math.floor(whole / 60)} min ago`;
  }
  return `${Math.floor(whole / 3600)} h ago`;
}

/**
 * A moment returned by the admin API (ISO 8601, UTC) in a given time zone:
 * `Oct 23, 2026, 14:05`.
 */
export function formatDateTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

/**
 * The label of one point of a time series (see `SeriesPoint.start`).
 *
 * A 24h period has one point per hour: its hour in the given time zone (`14:00`).
 * Longer periods have one point per UTC day: the day, always read in UTC
 * (`Oct 21`), because the bucket is a UTC day whatever the browser's time zone.
 */
export function formatBucket(
  iso: string,
  period: Period,
  timeZone: string,
): string {
  if (period === "24h") {
    return new Intl.DateTimeFormat(LOCALE, {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date(iso));
  }
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
  }).format(new Date(iso));
}

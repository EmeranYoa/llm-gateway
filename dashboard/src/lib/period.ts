import type { components } from "@/api/schema";

/** How far back a report of the admin API goes, until now. */
export type Period = components["schemas"]["Period"];

/** The periods the screens offer, shortest first. */
export const PERIODS: readonly Period[] = ["24h", "7d", "30d"];

export const DEFAULT_PERIOD: Period = "24h";

export const PERIOD_LABELS: Record<Period, string> = {
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};

/** A value of a URL search param, as Next.js gives it to a page. */
type SearchParamValue = string | string[] | undefined;

/** The period of the `period` search param, or the default (24h) when it is missing or invalid. */
export function parsePeriod(value: SearchParamValue): Period {
  const first = Array.isArray(value) ? value[0] : value;
  return PERIODS.find((period) => period === first) ?? DEFAULT_PERIOD;
}

/** The tenant of the `tenant` search param, or null (every tenant) when it is missing or empty. */
export function parseTenant(value: SearchParamValue): string | null {
  const first = Array.isArray(value) ? value[0] : value;
  return first ? first : null;
}

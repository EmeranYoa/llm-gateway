"use client";

import { useSyncExternalStore } from "react";

/**
 * Format a date and time for people: "23 Oct 2026, 14:05 CEST".
 *
 * `timeZone` undefined means the time zone of the browser.
 */
export function formatDateTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(iso));
}

const noSubscription = () => () => {};

/**
 * A time from the admin API (UTC), shown in the time zone of the browser.
 *
 * The server does not know that time zone: it renders the time in UTC, then the
 * browser renders it again in its own zone once the page is hydrated.
 */
export function LocalTime({ value }: { value: string }) {
  const inBrowser = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
  return (
    <time dateTime={value}>
      {formatDateTime(value, inBrowser ? undefined : "UTC")}
    </time>
  );
}

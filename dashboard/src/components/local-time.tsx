"use client";

import { useBrowserTimeZone } from "@/lib/browser-hooks";
import { formatDateTime } from "@/lib/format";
import { useLocale, useTranslator } from "@/lib/i18n/client";
import { richText } from "@/lib/i18n/rich-text";

/**
 * Times of the admin API (UTC) shown in the browser's time zone. On the server
 * render they show in UTC, then switch to the browser's zone once loaded.
 */

/**
 * A moment (ISO 8601) in the browser's time zone, in a `<time>` element.
 * `seconds` adds the seconds, for short events such as a request or a cooldown.
 */
export function LocalDateTime({
  iso,
  seconds = false,
}: {
  iso: string;
  seconds?: boolean;
}) {
  const timeZone = useBrowserTimeZone();
  const locale = useLocale();
  return (
    <time dateTime={iso}>
      {formatDateTime(locale, iso, timeZone, { seconds })}
    </time>
  );
}

/** Names the time zone the screen uses: "Times in Africa/Douala". */
export function TimeZoneName() {
  const t = useTranslator();
  return <span>{t("time.zone", { timeZone: useBrowserTimeZone() })}</span>;
}

/** The time range of a report, and the time zone it is shown in. */
export function PeriodRange({ start, end }: { start: string; end: string }) {
  const t = useTranslator();
  return (
    <p className="text-xs text-slate-600">
      {richText(t, "time.range", {
        start: <LocalDateTime iso={start} />,
        end: <LocalDateTime iso={end} />,
      })}{" "}
      · <TimeZoneName />
    </p>
  );
}

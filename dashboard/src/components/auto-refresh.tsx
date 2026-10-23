"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { usePageHidden } from "@/lib/browser-hooks";
import { formatAge } from "@/lib/format";

/** How often the data of a screen is reloaded. */
export const REFRESH_INTERVAL_MS = 10_000;

type AutoRefreshProps = {
  /**
   * When the data shown was produced, as ISO 8601 (for example the `end` of a
   * report of the admin API). Ignored when `failed` is true.
   */
  updatedAt: string | null;
  /**
   * True when the server page could not load its data. `children` is then the
   * error to show, used only when there is no earlier data for `dataKey`.
   */
  failed?: boolean;
  /**
   * What the data is about, e.g. `"7d|acme"` for the filters of the page. After
   * a failure, the last data is kept only if it was loaded for the same key: data
   * of other filters is never shown as if it were current.
   */
  dataKey: string;
  /** Milliseconds between two refreshes. Default: 10 s. */
  intervalMs?: number;
  children: React.ReactNode;
};

type Snapshot = {
  children: React.ReactNode;
  updatedAt: string | null;
  dataKey: string;
};

/**
 * Reload the server page every 10 s with `router.refresh()`: the server
 * components run again and React updates the page in place, so there is no
 * visible reload, and scroll and filters are kept.
 *
 * It shows "Updated N s ago" and a pause button. It pauses while the tab is
 * hidden. When a refresh fails, it keeps showing the last data with an
 * "Update failed" badge.
 */
export function AutoRefresh({
  updatedAt,
  failed = false,
  dataKey,
  intervalMs = REFRESH_INTERVAL_MS,
  children,
}: AutoRefreshProps) {
  const router = useRouter();
  const hidden = usePageHidden();
  const [paused, setPaused] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const [lastGood, setLastGood] = useState<Snapshot | null>(null);

  // Remember the last data that loaded well (state adjusted during render, as
  // recommended by React for state derived from props).
  if (!failed && lastGood?.children !== children) {
    setLastGood({ children, updatedAt, dataKey });
  }

  useEffect(() => {
    if (paused || hidden) {
      return;
    }
    const timer = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [paused, hidden, intervalMs, router]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const stale = failed && lastGood !== null && lastGood.dataKey === dataKey;
  const content = stale ? lastGood.children : children;
  const shownUpdatedAt = failed
    ? stale
      ? lastGood.updatedAt
      : null
    : updatedAt;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-slate-600">
        {shownUpdatedAt !== null && (
          <span>Updated {formatAge(ageInSeconds(shownUpdatedAt, now))}</span>
        )}
        {paused ? (
          <span>Auto-refresh paused</span>
        ) : (
          hidden && <span>Auto-refresh paused while the tab is hidden</span>
        )}
        <span role="status">
          {stale && (
            <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-900">
              Update failed
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={() => setPaused(!paused)}
          aria-label={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
          className="rounded border border-slate-300 bg-white px-2 py-0.5 text-slate-700 hover:bg-slate-100 focus:ring-2 focus:ring-sky-600 focus:outline-none"
        >
          {paused ? "Resume" : "Pause"}
        </button>
      </div>
      {content}
    </div>
  );
}

/** Seconds since `iso`. 0 until the first tick, so the server and the browser agree. */
function ageInSeconds(iso: string, now: number | null): number {
  if (now === null) {
    return 0;
  }
  return (now - Date.parse(iso)) / 1000;
}

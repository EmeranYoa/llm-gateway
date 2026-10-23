import { useSyncExternalStore } from "react";

/**
 * Hooks that read the browser, for client components.
 *
 * Both use `useSyncExternalStore`: the server render and the first browser
 * render use the server value, then React switches to the browser value. So
 * the HTML of the server always matches the first render (no hydration error).
 */

/** Time zone used on the server render, before the browser's is known. */
export const SERVER_TIME_ZONE = "UTC";

function subscribeNever(): () => void {
  return () => {};
}

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** The IANA time zone of the browser, e.g. `Africa/Douala` (`UTC` on the server). */
export function useBrowserTimeZone(): string {
  return useSyncExternalStore(
    subscribeNever,
    browserTimeZone,
    () => SERVER_TIME_ZONE,
  );
}

function subscribeToVisibility(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

/** True while the tab is hidden (Page Visibility API). False on the server. */
export function usePageHidden(): boolean {
  return useSyncExternalStore(
    subscribeToVisibility,
    () => document.visibilityState === "hidden",
    () => false,
  );
}

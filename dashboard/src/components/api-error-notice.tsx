import type { AdminApiError } from "@/api/client";

/** Show an error of the admin API on a page, instead of a blank error screen. */
export function ApiErrorNotice({ error }: { error: AdminApiError }) {
  return (
    <div
      role="alert"
      className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <p className="font-medium">The admin API returned an error.</p>
      <p>{error.message}</p>
      {error.status !== null && (
        <p className="mt-1 text-xs text-red-700">
          HTTP {error.status}
          {error.code && ` (${error.code})`}
        </p>
      )}
    </div>
  );
}

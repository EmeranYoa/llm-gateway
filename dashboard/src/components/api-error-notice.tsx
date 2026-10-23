import type { AdminApiError } from "@/api/client";
import { describeApiError } from "@/lib/i18n/api-errors";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

/**
 * Show an error of the admin API on a page, instead of a blank error screen.
 * The message is translated from the error `code`; an unknown code shows a
 * generic message and the English detail of the admin API.
 */
export function ApiErrorNotice({
  error,
  locale,
}: {
  error: AdminApiError;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  const { message, detail } = describeApiError(error, locale);
  return (
    <div
      role="alert"
      className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <p className="font-medium">{t("apiError.title")}</p>
      <p>{message}</p>
      {detail !== null && <p>{detail}</p>}
      {error.status !== null && (
        <p className="mt-1 text-xs text-red-700">
          HTTP {error.status}
          {error.code && ` (${error.code})`}
        </p>
      )}
    </div>
  );
}

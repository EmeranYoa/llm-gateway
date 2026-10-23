import Link from "next/link";

import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";
import { type RequestFilters, requestsHref } from "@/lib/request-filters";

type RequestsPaginationProps = {
  filters: RequestFilters;
  /** Cursor of the page shown, or null on the first page. */
  cursor: string | null;
  /** `next_cursor` of the page shown: null on the last page. */
  nextCursor: string | null;
  locale: Locale;
};

const LINK =
  "rounded border border-slate-300 bg-white px-3 py-1 text-sm text-slate-700 hover:bg-slate-100 focus:ring-2 focus:ring-sky-600 focus:outline-none";

/**
 * Links to the older page and back to the newest one, keeping the filters.
 * The admin API pages forwards only, so there is no "previous page" link.
 */
export function RequestsPagination({
  filters,
  cursor,
  nextCursor,
  locale,
}: RequestsPaginationProps) {
  if (cursor === null && nextCursor === null) {
    return null;
  }
  const t = getTranslator(locale);
  return (
    <nav aria-label={t("requests.pages")} className="flex flex-wrap gap-3">
      {cursor !== null && (
        <Link href={requestsHref(filters)} className={LINK}>
          {t("requests.newest")}
        </Link>
      )}
      {nextCursor !== null && (
        <Link href={requestsHref(filters, nextCursor)} className={LINK}>
          {t("requests.older")}
        </Link>
      )}
    </nav>
  );
}

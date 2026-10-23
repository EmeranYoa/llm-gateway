import { useId } from "react";

import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

type StatCardProps = {
  /** Name of the figure, e.g. "Error rate". */
  label: string;
  /** The figure, already formatted (see `src/lib/format.ts`). */
  value: string;
  /** Exact definition of the figure, shown in a tooltip next to the label. */
  definition: string;
  /** Optional line under the value: a breakdown, a second percentile... */
  detail?: React.ReactNode;
  /** Optional warning under the value, e.g. "3 requests without a price". */
  warning?: string;
  /** Language of the page, for the name of the "i" button. */
  locale: Locale;
};

/**
 * One key figure of a screen: a label, a big value and a tooltip with the
 * definition of the figure. The tooltip opens on hover and on keyboard focus
 * of the "i" button, and is linked to it with `aria-describedby`.
 */
export function StatCard({
  label,
  value,
  definition,
  detail,
  warning,
  locale,
}: StatCardProps) {
  const tooltipId = useId();
  const t = getTranslator(locale);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-1.5">
        <h3 className="text-sm font-medium text-slate-600">{label}</h3>
        <span className="group relative inline-flex">
          <button
            type="button"
            aria-label={t("statCard.definitionOf", { label })}
            aria-describedby={tooltipId}
            className="inline-flex size-4 items-center justify-center rounded-full border border-slate-400 text-[10px] leading-none font-semibold text-slate-600 hover:border-slate-700 hover:text-slate-900 focus:ring-2 focus:ring-sky-600 focus:outline-none"
          >
            i
          </button>
          <span
            role="tooltip"
            id={tooltipId}
            className="absolute top-6 left-1/2 z-10 hidden w-64 -translate-x-1/2 rounded bg-slate-900 px-3 py-2 text-xs font-normal text-white shadow-lg group-focus-within:block group-hover:block"
          >
            {definition}
          </span>
        </span>
      </div>
      <p className="mt-1 text-2xl font-semibold text-slate-900 tabular-nums">
        {value}
      </p>
      {detail && <p className="mt-1 text-xs text-slate-600">{detail}</p>}
      {warning && (
        <p className="mt-1 text-xs font-medium text-amber-800">⚠ {warning}</p>
      )}
    </div>
  );
}

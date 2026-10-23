/** Feedback of the forms of the Keys screen, announced by screen readers. */

import { useLocale } from "@/lib/i18n/client";
import { describeKeyError } from "@/lib/i18n/key-errors";
import type { KeyFormError } from "@/lib/key-forms";

/** The error of a form, in the language of the page (for client components). */
export function ErrorMessage({ error }: { error: KeyFormError }) {
  const { message, detail } = describeKeyError(error, useLocale());
  return (
    <p
      role="alert"
      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
    >
      {message}
      {detail !== null && <span className="block text-xs">{detail}</span>}
    </p>
  );
}

export function SuccessMessage({ children }: { children: React.ReactNode }) {
  return (
    <p
      role="status"
      className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
    >
      {children}
    </p>
  );
}

/** Shared look of the inputs and buttons of the Keys screen. */
export const inputClass =
  "w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none";

export const primaryButtonClass =
  "rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60";

export const secondaryButtonClass =
  "rounded border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-100 disabled:opacity-60";

export const dangerButtonClass =
  "rounded bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-60";

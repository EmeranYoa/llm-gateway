"use client";

import type { AuthFormError } from "@/lib/auth-forms";
import { describeAuthError } from "@/lib/i18n/auth-errors";
import { useLocale, useTranslator } from "@/lib/i18n/client";

/** Building blocks of the sign-in, setup, password and recovery forms. */

type FieldProps = {
  /** The `name` posted to the server action, also the base of the input id. */
  name: string;
  label: string;
  type?: "text" | "password";
  /** `username`, `current-password`, `new-password`, or `off`. */
  autoComplete: string;
  /** A short help text under the field. */
  hint?: React.ReactNode;
  /** Secrets typed from a log line: monospace, no spell check. */
  monospace?: boolean;
};

export function Field({
  name,
  label,
  type = "text",
  autoComplete,
  hint,
  monospace = false,
}: FieldProps) {
  const id = `auth-${name}`;
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        required
        autoComplete={autoComplete}
        spellCheck={false}
        autoCapitalize="none"
        aria-describedby={hint === undefined ? undefined : hintId}
        className={`rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none ${monospace ? "font-mono" : ""}`}
      />
      {hint !== undefined && (
        <p id={hintId} className="text-xs text-slate-600">
          {hint}
        </p>
      )}
    </div>
  );
}

/** The error of a form, in the language of the page, announced by screen readers. */
export function FormError({ error }: { error: AuthFormError | null }) {
  const locale = useLocale();
  if (error === null) {
    return null;
  }
  const { message, detail } = describeAuthError(error, locale);
  return (
    <div
      role="alert"
      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
    >
      <p>{message}</p>
      {detail !== null && <p className="mt-1 text-xs">{detail}</p>}
    </div>
  );
}

export function SubmitButton({
  pending,
  children,
}: {
  pending: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
    >
      {children}
    </button>
  );
}

/** Where the setup and recovery tokens are printed. */
const ADMIN_API_LOGS_COMMAND = "docker compose logs admin-api";

/** The hint of a token field: the command that shows the admin API logs. */
export function TokenHint() {
  const t = useTranslator();
  return (
    <>
      {t("auth.tokenHint")}{" "}
      <code className="font-mono">{ADMIN_API_LOGS_COMMAND}</code>
    </>
  );
}

import type { AuthFormError } from "@/lib/auth-forms";
import { formatWait } from "@/lib/format";

import { describeApiError } from "./api-errors";
import type { Locale } from "./locale";
import { getTranslator } from "./translator";

/**
 * The error of a sign-in, setup, password or recovery form in the operator's
 * language: a check of the form, or an error of the admin API translated from
 * its code. Too many sign-in attempts says how long to wait, from `Retry-After`.
 */
export function describeAuthError(
  error: AuthFormError,
  locale: Locale,
): { message: string; detail: string | null } {
  const t = getTranslator(locale);
  if (error.kind === "form") {
    return { message: t(`auth.problems.${error.problem}`), detail: null };
  }
  if (error.code === "too_many_attempts" && error.retryAfterSeconds !== null) {
    return {
      message: t("auth.tooManyAttemptsWait", {
        wait: formatWait(locale, error.retryAfterSeconds),
      }),
      detail: null,
    };
  }
  return describeApiError(error, locale);
}

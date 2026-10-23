import type { KeyFormError } from "@/lib/key-forms";

import { isKnownErrorCode } from "./api-errors";
import type { Locale } from "./locale";
import { getTranslator } from "./translator";

/**
 * The error of a form of the Keys screen in the operator's language: a check
 * of the form, or an error of the admin API.
 *
 * A known error `code` gives its translated message. Any other error says what
 * kind of error it is (values refused, or an HTTP error) and gives the English
 * message of the admin API as `detail`, so nothing useful is lost.
 */
export function describeKeyError(
  error: KeyFormError,
  locale: Locale,
): { message: string; detail: string | null } {
  const t = getTranslator(locale);
  if (error.kind === "form") {
    if (error.problem === "notWholeNumber" || error.problem === "tooLarge") {
      const field = t(`keys.fields.${error.field}`);
      return {
        message: t(`keys.problems.${error.problem}`, { field }),
        detail: null,
      };
    }
    return { message: t(`keys.problems.${error.problem}`), detail: null };
  }
  if (isKnownErrorCode(error.code)) {
    return { message: t(`apiError.codes.${error.code}`), detail: null };
  }
  const detail = t("apiError.englishDetail", { detail: error.message });
  if (error.status === 400) {
    return { message: t("keys.errors.refusedValues"), detail };
  }
  if (error.status !== null) {
    return {
      message: t("keys.errors.httpError", { status: String(error.status) }),
      detail,
    };
  }
  return { message: t("apiError.generic"), detail };
}

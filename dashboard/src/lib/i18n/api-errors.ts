import type { AdminApiError } from "@/api/client";
import { en } from "@/messages/en";

import type { Locale } from "./locale";
import { getTranslator } from "./translator";

/** The error codes of the admin API that have their own message. */
export type KnownErrorCode = keyof typeof en.apiError.codes;

export function isKnownErrorCode(code: string | null): code is KnownErrorCode {
  return code !== null && Object.hasOwn(en.apiError.codes, code);
}

/**
 * An error of the admin API in the operator's language.
 *
 * A known `code` gives its translated message. Any other error gives a generic
 * translated message, and `detail`: the English message of the admin API, so
 * nothing useful is lost.
 */
export function describeApiError(
  error: Pick<AdminApiError, "code" | "message">,
  locale: Locale,
): { message: string; detail: string | null } {
  const t = getTranslator(locale);
  if (isKnownErrorCode(error.code)) {
    return { message: t(`apiError.codes.${error.code}`), detail: null };
  }
  return {
    message: t("apiError.generic"),
    detail: t("apiError.englishDetail", { detail: error.message }),
  };
}

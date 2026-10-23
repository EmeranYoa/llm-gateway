"use server";

import { AdminApiError } from "@/api/client";
import { setAccountLanguage } from "@/api/operators";
import { isLocale } from "@/lib/i18n/locale";

/**
 * Save the language chosen in the nav bar in the signed-in operator's account,
 * so it follows them on every device. The selector also writes the `lang`
 * cookie, which keeps the language on the sign-in page after sign-out.
 *
 * Returns whether the account was updated. A session refused by the admin API
 * redirects, like every call with the session.
 */
export async function saveLanguageAction(
  language: string,
): Promise<{ saved: boolean }> {
  if (!isLocale(language)) {
    return { saved: false };
  }
  try {
    await setAccountLanguage(language);
    return { saved: true };
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { saved: false };
    }
    throw error;
  }
}

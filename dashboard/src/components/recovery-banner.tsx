import { keepApiError } from "@/api/client";
import { getRecoveryStatus } from "@/api/operators";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";

/**
 * A warning on every page, signed in or not, while account recovery is on:
 * anyone with the recovery token can reset a password, so it must be turned
 * off once the operator is back in. Nothing is shown when the admin API cannot
 * say (the page shows its own errors).
 */
export async function RecoveryBanner({ locale }: { locale: Locale }) {
  const enabled = await getRecoveryStatus().catch(keepApiError);
  if (enabled !== true) {
    return null;
  }
  const t = getTranslator(locale);
  return (
    <div
      role="status"
      className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900"
    >
      {t("recovery.banner")}
    </div>
  );
}

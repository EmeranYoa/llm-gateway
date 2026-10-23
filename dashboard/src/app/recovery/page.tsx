import Link from "next/link";
import { redirect } from "next/navigation";

import { keepApiError } from "@/api/client";
import { getRecoveryStatus } from "@/api/operators";
import { AuthCard } from "@/components/auth/auth-card";
import { RecoveryForm } from "@/components/auth/recovery-form";
import { recoverAction } from "@/lib/auth-actions";
import { getI18n } from "@/lib/i18n/server";

/**
 * Account recovery, while the admin API runs with `OPERATOR_RECOVERY=true`:
 * the one-time recovery token of its logs sets a new password for an account.
 * Without recovery, the sign-in page replaces it.
 */
export default async function RecoveryPage() {
  const enabled = await getRecoveryStatus().catch(keepApiError);
  if (enabled === false) {
    redirect("/login");
  }
  const { t } = await getI18n();

  return (
    <AuthCard title={t("recovery.title")} intro={t("recovery.intro")}>
      <div className="flex flex-col gap-4">
        <RecoveryForm action={recoverAction} />
        <Link href="/login" className="text-sm text-sky-700 hover:underline">
          {t("recovery.signInLink")}
        </Link>
      </div>
    </AuthCard>
  );
}

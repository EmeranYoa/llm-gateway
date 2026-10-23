import { redirect } from "next/navigation";

import { keepApiError } from "@/api/client";
import { getSetupStatus } from "@/api/operators";
import { AuthCard } from "@/components/auth/auth-card";
import { SetupForm } from "@/components/auth/setup-form";
import { setUpAction } from "@/lib/auth-actions";
import { getI18n } from "@/lib/i18n/server";

/**
 * Creation of the first operator account, with the one-time setup token
 * printed in the admin API logs. Once an account exists, the sign-in page
 * replaces it. When the admin API cannot say, the form is shown: a submit then
 * reports the error.
 */
export default async function SetupPage() {
  const open = await getSetupStatus().catch(keepApiError);
  if (open === false) {
    redirect("/login");
  }
  const { t } = await getI18n();

  return (
    <AuthCard title={t("setup.title")} intro={t("setup.intro")}>
      <SetupForm action={setUpAction} />
    </AuthCard>
  );
}

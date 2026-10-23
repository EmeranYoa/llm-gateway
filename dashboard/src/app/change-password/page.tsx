import { redirect } from "next/navigation";

import { SESSION_EXPIRED_PATH } from "@/api/client";
import { AuthCard } from "@/components/auth/auth-card";
import { ChangePasswordForm } from "@/components/auth/change-password-form";
import { loadAccount } from "@/lib/account";
import { changePasswordAction, signOutAction } from "@/lib/auth-actions";
import { getI18n } from "@/lib/i18n/server";
import { saveLanguageAction } from "@/lib/language-actions";

/**
 * Password change of the signed-in operator. The protected pages send here an
 * operator who must change their password (first sign-in after a reset or a
 * recovery): nothing else works until it is done. Outside the protected
 * layout, so its own redirect never loops; the proxy still requires a session.
 */
export default async function ChangePasswordPage() {
  const account = await loadAccount();
  if (account.status === "signed-out") {
    redirect("/login");
  }
  if (account.status === "expired") {
    redirect(SESSION_EXPIRED_PATH);
  }
  const forced =
    account.status === "signed-in" && account.me.must_change_password;
  const { t } = await getI18n();

  return (
    <AuthCard
      title={t("changePassword.title")}
      intro={forced ? t("changePassword.required") : undefined}
      // Until the password is changed, the admin API refuses to save the
      // language (403): the selector then only writes the cookie.
      saveLanguage={
        account.status === "signed-in" && !forced
          ? saveLanguageAction
          : undefined
      }
    >
      <div className="flex flex-col gap-4">
        <ChangePasswordForm action={changePasswordAction} />
        <form action={signOutAction}>
          <button
            type="submit"
            className="text-sm text-slate-600 hover:text-slate-900 hover:underline"
          >
            {t("nav.signOut")}
          </button>
        </form>
      </div>
    </AuthCard>
  );
}

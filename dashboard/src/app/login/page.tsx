import Link from "next/link";
import { redirect } from "next/navigation";

import { keepApiError } from "@/api/client";
import { getRecoveryStatus, getSetupStatus } from "@/api/operators";
import { AuthCard } from "@/components/auth/auth-card";
import { SignInForm } from "@/components/auth/sign-in-form";
import { signInAction } from "@/lib/auth-actions";
import { getI18n } from "@/lib/i18n/server";

/**
 * Sign-in with a username and a password. While no account exists, the setup
 * of the first one replaces it. When the admin API cannot say, the form is
 * shown: a sign-in then reports the error.
 */
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { expired } = await searchParams;
  const [setupOpen, recoveryEnabled] = await Promise.all([
    getSetupStatus().catch(keepApiError),
    getRecoveryStatus().catch(keepApiError),
  ]);
  if (setupOpen === true) {
    redirect("/setup");
  }
  const { t } = await getI18n();

  return (
    <AuthCard title={t("signIn.title")} intro={t("signIn.intro")}>
      <div className="flex flex-col gap-4">
        {expired === "1" && (
          <p
            role="status"
            className="rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900"
          >
            {t("session.expired")}
          </p>
        )}
        <SignInForm action={signInAction} />
        {recoveryEnabled === true && (
          <Link
            href="/recovery"
            className="text-sm text-sky-700 hover:underline"
          >
            {t("signIn.recoveryLink")}
          </Link>
        )}
      </div>
    </AuthCard>
  );
}

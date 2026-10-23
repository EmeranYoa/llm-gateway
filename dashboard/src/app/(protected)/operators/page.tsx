import { AdminApiError, keepApiError } from "@/api/client";
import { listOperators } from "@/api/operators";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { ChangeOwnPasswordForm } from "@/components/operators/change-own-password-form";
import { CreateOperatorForm } from "@/components/operators/create-operator-form";
import { OperatorsTable } from "@/components/operators/operators-table";
import { loadAccount } from "@/lib/account";
import { getI18n } from "@/lib/i18n/server";
import {
  changeOwnPasswordAction,
  createOperatorAction,
  disableOperatorAction,
  enableOperatorAction,
  resetOperatorPasswordAction,
} from "@/lib/operator-actions";

/** The server actions of the rows of the list. */
const ROW_ACTIONS = {
  reset: resetOperatorPasswordAction,
  disable: disableOperatorAction,
  enable: enableOperatorAction,
};

/**
 * Operators screen: the accounts that can sign in to the dashboard, and the
 * forms that create them, reset their password, disable or enable them, and
 * change your own password. Each action asks for your current password again.
 *
 * It does not refresh by itself (it would disturb a form being filled); each
 * server action revalidates it instead.
 */
export default async function OperatorsPage() {
  const { locale, t } = await getI18n();
  const [operators, account] = await Promise.all([
    listOperators().catch(keepApiError),
    // Read once per request: the protected layout has read it already.
    loadAccount(),
  ]);
  const currentUsername =
    account.status === "signed-in" ? account.me.username : null;

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="mb-1 text-xl font-semibold">{t("operators.title")}</h1>
        <p className="text-sm text-slate-600">{t("operators.intro")}</p>
      </header>

      <section
        aria-labelledby="accounts-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="accounts-heading" className="text-lg font-semibold">
          {t("operators.listTitle")}
        </h2>
        {operators instanceof AdminApiError ? (
          <ApiErrorNotice error={operators} locale={locale} />
        ) : (
          <OperatorsTable
            operators={operators}
            currentUsername={currentUsername}
            actions={ROW_ACTIONS}
          />
        )}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section
          aria-labelledby="create-heading"
          className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 id="create-heading" className="text-lg font-semibold">
            {t("operators.create.title")}
          </h2>
          <CreateOperatorForm action={createOperatorAction} />
        </section>

        <section
          aria-labelledby="own-password-heading"
          className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 id="own-password-heading" className="text-lg font-semibold">
            {t("operators.own.title")}
          </h2>
          <p className="text-sm text-slate-600">{t("operators.own.intro")}</p>
          <ChangeOwnPasswordForm action={changeOwnPasswordAction} />
        </section>
      </div>
    </div>
  );
}

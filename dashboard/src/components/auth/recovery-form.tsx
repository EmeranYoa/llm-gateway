"use client";

import { checkRecoveryForm, type RecoveryFormState } from "@/lib/auth-forms";
import { useTranslator } from "@/lib/i18n/client";

import { Field, FormError, SubmitButton, TokenHint } from "./form-parts";
import { useAuthForm } from "./use-auth-form";

type RecoveryFormProps = {
  /** The `recoverAction` server action. A prop, so tests can pass a fake one. */
  action: (
    state: RecoveryFormState,
    form: FormData,
  ) => Promise<RecoveryFormState>;
};

const INITIAL_STATE: RecoveryFormState = {
  error: null,
  recoveredUsername: null,
};

/**
 * Set a new password for an account with the recovery token. A success says to
 * sign in with the new password, which must then be changed.
 */
export function RecoveryForm({ action }: RecoveryFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useAuthForm(
    action,
    INITIAL_STATE,
    checkRecoveryForm,
  );

  if (state.recoveredUsername !== null) {
    // The page links to the sign-in under the form.
    return (
      <p
        role="status"
        className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
      >
        {t("recovery.done", { username: state.recoveredUsername })}
      </p>
    );
  }

  return (
    <form
      ref={formRef}
      onSubmit={onSubmit}
      noValidate
      className="flex flex-col gap-4"
    >
      <Field
        name="token"
        label={t("recovery.token")}
        autoComplete="off"
        monospace
        hint={<TokenHint />}
      />
      <Field
        name="username"
        label={t("auth.username")}
        autoComplete="username"
      />
      <Field
        name="newPassword"
        label={t("auth.newPassword")}
        type="password"
        autoComplete="new-password"
        hint={t("auth.passwordRule")}
      />
      <Field
        name="newPasswordAgain"
        label={t("auth.newPasswordAgain")}
        type="password"
        autoComplete="new-password"
      />
      <FormError error={state.error} />
      <SubmitButton pending={pending}>{t("recovery.submit")}</SubmitButton>
    </form>
  );
}

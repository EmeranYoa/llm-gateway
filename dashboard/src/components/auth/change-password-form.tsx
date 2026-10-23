"use client";

import { type AuthFormState, checkPasswordChangeForm } from "@/lib/auth-forms";
import { useTranslator } from "@/lib/i18n/client";

import { Field, FormError, SubmitButton } from "./form-parts";
import { useAuthForm } from "./use-auth-form";

type ChangePasswordFormProps = {
  /** The `changePasswordAction` server action. A prop, so tests can pass a fake one. */
  action: (state: AuthFormState, form: FormData) => Promise<AuthFormState>;
};

const INITIAL_STATE: AuthFormState = { error: null };

/** Current password, then the new one twice. A success opens the overview. */
export function ChangePasswordForm({ action }: ChangePasswordFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useAuthForm(
    action,
    INITIAL_STATE,
    checkPasswordChangeForm,
  );

  return (
    <form
      ref={formRef}
      onSubmit={onSubmit}
      noValidate
      className="flex flex-col gap-4"
    >
      <Field
        name="currentPassword"
        label={t("auth.currentPassword")}
        type="password"
        autoComplete="current-password"
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
      <SubmitButton pending={pending}>
        {t("changePassword.submit")}
      </SubmitButton>
    </form>
  );
}

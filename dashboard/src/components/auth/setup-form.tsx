"use client";

import { type AuthFormState, checkSetupForm } from "@/lib/auth-forms";
import { useTranslator } from "@/lib/i18n/client";

import { Field, FormError, SubmitButton, TokenHint } from "./form-parts";
import { useAuthForm } from "./use-auth-form";

type SetupFormProps = {
  /** The `setUpAction` server action. A prop, so tests can pass a fake one. */
  action: (state: AuthFormState, form: FormData) => Promise<AuthFormState>;
};

const INITIAL_STATE: AuthFormState = { error: null };

/**
 * Create the first operator account with the setup token. A success signs the
 * operator in and opens the overview (a redirect of the action).
 */
export function SetupForm({ action }: SetupFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useAuthForm(
    action,
    INITIAL_STATE,
    checkSetupForm,
  );

  return (
    <form
      ref={formRef}
      onSubmit={onSubmit}
      noValidate
      className="flex flex-col gap-4"
    >
      <Field
        name="token"
        label={t("setup.token")}
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
        name="password"
        label={t("auth.password")}
        type="password"
        autoComplete="new-password"
        hint={t("auth.passwordRule")}
      />
      <Field
        name="passwordAgain"
        label={t("auth.passwordAgain")}
        type="password"
        autoComplete="new-password"
      />
      <FormError error={state.error} />
      <SubmitButton pending={pending}>{t("setup.submit")}</SubmitButton>
    </form>
  );
}

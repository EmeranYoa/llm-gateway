"use client";

import { type AuthFormState, checkSignInForm } from "@/lib/auth-forms";
import { useTranslator } from "@/lib/i18n/client";

import { Field, FormError, SubmitButton } from "./form-parts";
import { useAuthForm } from "./use-auth-form";

type SignInFormProps = {
  /** The `signInAction` server action. A prop, so tests can pass a fake one. */
  action: (state: AuthFormState, form: FormData) => Promise<AuthFormState>;
};

const INITIAL_STATE: AuthFormState = { error: null };

/** Username and password. A success opens the overview (a redirect of the action). */
export function SignInForm({ action }: SignInFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useAuthForm(
    action,
    INITIAL_STATE,
    checkSignInForm,
  );

  return (
    <form
      ref={formRef}
      onSubmit={onSubmit}
      noValidate
      className="flex flex-col gap-4"
    >
      <Field
        name="username"
        label={t("auth.username")}
        autoComplete="username"
      />
      <Field
        name="password"
        label={t("auth.password")}
        type="password"
        autoComplete="current-password"
      />
      <FormError error={state.error} />
      <SubmitButton pending={pending}>{t("signIn.submit")}</SubmitButton>
    </form>
  );
}

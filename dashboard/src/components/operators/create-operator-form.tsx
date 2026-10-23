"use client";

import { Field, FormError, SubmitButton } from "@/components/auth/form-parts";
import { SuccessMessage } from "@/components/keys/form-feedback";
import { useTranslator } from "@/lib/i18n/client";
import {
  checkNewOperatorForm,
  type OperatorFormState,
} from "@/lib/operator-forms";

import { CurrentPasswordField } from "./current-password-field";
import { useOperatorForm } from "./use-operator-form";

type CreateOperatorFormProps = {
  /** The `createOperatorAction` server action. A prop, so tests can pass a fake one. */
  action: (
    state: OperatorFormState,
    form: FormData,
  ) => Promise<OperatorFormState>;
};

const INITIAL_STATE: OperatorFormState = { error: null, done: null };
const ID_PREFIX = "new-operator";

/**
 * Create an operator account: a username and its first password typed twice,
 * confirmed with your current password. Its owner must change the password at
 * the first sign-in.
 */
export function CreateOperatorForm({ action }: CreateOperatorFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useOperatorForm(
    action,
    INITIAL_STATE,
    checkNewOperatorForm,
  );

  return (
    <form
      ref={formRef}
      onSubmit={onSubmit}
      noValidate
      className="flex max-w-md flex-col gap-4"
    >
      <Field
        idPrefix={ID_PREFIX}
        name="username"
        label={t("auth.username")}
        autoComplete="off"
      />
      <Field
        idPrefix={ID_PREFIX}
        name="password"
        label={t("auth.password")}
        type="password"
        autoComplete="new-password"
        hint={t("auth.passwordRule")}
      />
      <Field
        idPrefix={ID_PREFIX}
        name="passwordAgain"
        label={t("auth.passwordAgain")}
        type="password"
        autoComplete="new-password"
      />
      <p className="text-sm text-slate-600">{t("operators.create.note")}</p>
      <CurrentPasswordField idPrefix={ID_PREFIX} />
      <FormError error={state.error} />
      {state.error === null && state.done !== null && (
        <SuccessMessage>
          {t("operators.create.done", { username: state.done.username })}
        </SuccessMessage>
      )}
      <div>
        <SubmitButton pending={pending}>
          {t("operators.create.submit")}
        </SubmitButton>
      </div>
    </form>
  );
}

"use client";

import { Field, FormError, SubmitButton } from "@/components/auth/form-parts";
import { SuccessMessage } from "@/components/keys/form-feedback";
import { checkPasswordChangeForm } from "@/lib/auth-forms";
import { useTranslator } from "@/lib/i18n/client";
import type { OwnPasswordFormState } from "@/lib/operator-forms";

import { useOperatorForm } from "./use-operator-form";

type ChangeOwnPasswordFormProps = {
  /** The `changeOwnPasswordAction` server action. A prop, so tests can pass a fake one. */
  action: (
    state: OwnPasswordFormState,
    form: FormData,
  ) => Promise<OwnPasswordFormState>;
};

const INITIAL_STATE: OwnPasswordFormState = { error: null, changed: false };
const ID_PREFIX = "own-password";

/**
 * Change your own password: the current one, then the new one twice. The
 * page stays open; the admin API closes your other sessions.
 */
export function ChangeOwnPasswordForm({ action }: ChangeOwnPasswordFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useOperatorForm(
    action,
    INITIAL_STATE,
    checkPasswordChangeForm,
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
        name="currentPassword"
        label={t("auth.currentPassword")}
        type="password"
        autoComplete="current-password"
      />
      <Field
        idPrefix={ID_PREFIX}
        name="newPassword"
        label={t("auth.newPassword")}
        type="password"
        autoComplete="new-password"
        hint={t("auth.passwordRule")}
      />
      <Field
        idPrefix={ID_PREFIX}
        name="newPasswordAgain"
        label={t("auth.newPasswordAgain")}
        type="password"
        autoComplete="new-password"
      />
      <FormError error={state.error} />
      {state.error === null && state.changed && (
        <SuccessMessage>{t("operators.own.done")}</SuccessMessage>
      )}
      <div>
        <SubmitButton pending={pending}>
          {t("operators.own.submit")}
        </SubmitButton>
      </div>
    </form>
  );
}

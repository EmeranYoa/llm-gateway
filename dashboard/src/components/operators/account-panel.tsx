"use client";

import { type KeyboardEvent, useEffect } from "react";

import { Field, FormError } from "@/components/auth/form-parts";
import {
  dangerButtonClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/keys/form-feedback";
import { useTranslator } from "@/lib/i18n/client";
import {
  checkPasswordResetForm,
  checkReauthenticationForm,
  type Operator,
  type OperatorActionKind,
  type OperatorFormState,
} from "@/lib/operator-forms";

import { CurrentPasswordField } from "./current-password-field";
import { useOperatorForm } from "./use-operator-form";

/** A server action of a row: reset a password, disable or enable an account. */
export type OperatorFormAction = (
  state: OperatorFormState,
  form: FormData,
) => Promise<OperatorFormState>;

type AccountPanelProps = {
  operator: Operator;
  kind: OperatorActionKind;
  /** The server action of `kind`. A prop, so tests can pass a fake one. */
  action: OperatorFormAction;
  /** Called with the success message once the admin API made the change. */
  onDone: (message: string) => void;
  onCancel: () => void;
};

const INITIAL_STATE: OperatorFormState = { error: null, done: null };

/**
 * The form of an action on another operator's account, opened under its row:
 * the new password twice for a reset, then your current password.
 *
 * Disabling is the confirmation step itself: an `alertdialog` that names the
 * account and says what happens. The panel takes the focus on its first field
 * and closes with Escape or Cancel.
 */
export function AccountPanel({
  operator,
  kind,
  action,
  onDone,
  onCancel,
}: AccountPanelProps) {
  const t = useTranslator();
  const { state, onSubmit, pending, formRef } = useOperatorForm(
    action,
    INITIAL_STATE,
    kind === "reset" ? checkPasswordResetForm : checkReauthenticationForm,
    (next) => {
      if (next.done !== null) {
        onDone(t(`operators.${kind}.done`, { username: next.done.username }));
      }
    },
  );

  useEffect(() => {
    formRef.current
      ?.querySelector<HTMLInputElement>("input:not([type=hidden])")
      ?.focus();
  }, [formRef]);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape" && !pending) {
      onCancel();
    }
  }

  const idPrefix = `${kind}-${operator.id}`;
  const titleId = `${idPrefix}-title`;
  const descriptionId = `${idPrefix}-description`;
  const danger = kind === "disable";
  return (
    <div
      role={danger ? "alertdialog" : "group"}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={onKeyDown}
      className={`flex flex-col gap-3 rounded border p-4 text-left ${
        danger ? "border-red-200 bg-red-50" : "border-slate-200 bg-slate-50"
      }`}
    >
      <p id={titleId} className="font-semibold">
        {t(`operators.${kind}.title`, { username: operator.username })}
      </p>
      <p id={descriptionId} className="text-sm text-slate-700">
        {t(`operators.${kind}.description`)}
      </p>
      <form
        ref={formRef}
        onSubmit={onSubmit}
        noValidate
        className="flex max-w-md flex-col gap-3"
      >
        <input type="hidden" name="operatorId" value={operator.id} />
        {kind === "reset" && (
          <>
            <Field
              idPrefix={idPrefix}
              name="password"
              label={t("auth.newPassword")}
              type="password"
              autoComplete="new-password"
              hint={t("auth.passwordRule")}
            />
            <Field
              idPrefix={idPrefix}
              name="passwordAgain"
              label={t("auth.newPasswordAgain")}
              type="password"
              autoComplete="new-password"
            />
          </>
        )}
        <CurrentPasswordField idPrefix={idPrefix} />
        <FormError error={state.error} />
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={pending}
            className={danger ? dangerButtonClass : primaryButtonClass}
          >
            {t(`operators.${kind}.submit`)}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={onCancel}
            className={secondaryButtonClass}
          >
            {t("operators.cancel")}
          </button>
        </div>
      </form>
    </div>
  );
}

"use client";

import type { Limits } from "@/api/tenant-keys";
import { useTranslator } from "@/lib/i18n/client";
import type { Translator } from "@/lib/i18n/translator";
import type { LimitsState } from "@/lib/key-actions";
import { checkLimitsForm } from "@/lib/key-forms";

import {
  ErrorMessage,
  inputClass,
  primaryButtonClass,
  SuccessMessage,
} from "./form-feedback";
import { useCheckedAction } from "./use-checked-action";

type LimitsFormProps = {
  /** The `setLimitsAction` server action. A prop, so tests can pass a fake one. */
  action: (state: LimitsState, form: FormData) => Promise<LimitsState>;
  tenant: string;
  /** The limits the gateway applies now, shown as hints. */
  effectiveLimits: Limits;
};

const IDLE: LimitsState = { status: "idle" };

function hint(t: Translator, value: number | null): string {
  return value === null
    ? t("keys.limits.nowNoLimit")
    : t("keys.limits.now", { value: String(value) });
}

/** Change the own limits of a tenant: at least one, positive whole numbers. */
export function LimitsForm({
  action,
  tenant,
  effectiveLimits,
}: LimitsFormProps) {
  const t = useTranslator();
  const { state, onSubmit, pending } = useCheckedAction<LimitsState>(
    action,
    IDLE,
    checkLimitsForm,
  );

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3">
      <input type="hidden" name="tenant" value={tenant} />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="limits-rpm" className="text-sm font-medium">
            {t("keys.fields.rpm")}
          </label>
          <input
            id="limits-rpm"
            name="rpm"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder={hint(t, effectiveLimits.rpm)}
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="limits-tokens" className="text-sm font-medium">
            {t("keys.fields.tokens_per_day")}
          </label>
          <input
            id="limits-tokens"
            name="tokens_per_day"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder={hint(t, effectiveLimits.tokens_per_day)}
            className={inputClass}
          />
        </div>
      </div>
      <p className="text-xs text-slate-600">{t("keys.limits.hint")}</p>
      {state.status === "error" && <ErrorMessage error={state.error} />}
      {state.status === "saved" && (
        <SuccessMessage>{t("keys.limits.saved")}</SuccessMessage>
      )}
      <div>
        <button type="submit" disabled={pending} className={primaryButtonClass}>
          {t("keys.limits.submit")}
        </button>
      </div>
    </form>
  );
}

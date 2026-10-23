"use client";

import type { Limits } from "@/api/tenant-keys";
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

function hint(value: number | null): string {
  return value === null ? "now: no limit" : `now: ${value}`;
}

/** Change the own limits of a tenant: at least one, positive whole numbers. */
export function LimitsForm({
  action,
  tenant,
  effectiveLimits,
}: LimitsFormProps) {
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
            Requests per minute
          </label>
          <input
            id="limits-rpm"
            name="rpm"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder={hint(effectiveLimits.rpm)}
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="limits-tokens" className="text-sm font-medium">
            Tokens per day
          </label>
          <input
            id="limits-tokens"
            name="tokens_per_day"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder={hint(effectiveLimits.tokens_per_day)}
            className={inputClass}
          />
        </div>
      </div>
      <p className="text-xs text-slate-600">
        Give at least one. A field left empty keeps its value. Gateways apply
        new limits within 60 seconds.
      </p>
      {state.status === "error" && <ErrorMessage message={state.message} />}
      {state.status === "saved" && (
        <SuccessMessage>Limits saved.</SuccessMessage>
      )}
      <div>
        <button type="submit" disabled={pending} className={primaryButtonClass}>
          Save limits
        </button>
      </div>
    </form>
  );
}

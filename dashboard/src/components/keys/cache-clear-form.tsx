"use client";

import type { CacheClearState } from "@/lib/key-actions";
import { checkCacheClearForm } from "@/lib/key-forms";

import {
  ErrorMessage,
  inputClass,
  secondaryButtonClass,
  SuccessMessage,
} from "./form-feedback";
import { useCheckedAction } from "./use-checked-action";

type CacheClearFormProps = {
  /** The `clearCacheAction` server action. A prop, so tests can pass a fake one. */
  action: (state: CacheClearState, form: FormData) => Promise<CacheClearState>;
  tenant: string;
};

const IDLE: CacheClearState = { status: "idle" };

function describeResult(removed: number, alias: string | null): string {
  const answers =
    removed === 1 ? "1 cached answer" : `${removed} cached answers`;
  const scope = alias === null ? "every alias" : `alias ${alias}`;
  return `Removed ${answers} (${scope}).`;
}

/** Remove the cached answers of a tenant, or of one of its aliases. */
export function CacheClearForm({ action, tenant }: CacheClearFormProps) {
  const { state, onSubmit, pending } = useCheckedAction<CacheClearState>(
    action,
    IDLE,
    checkCacheClearForm,
  );

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3">
      <input type="hidden" name="tenant" value={tenant} />
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-48 flex-1 flex-col gap-1">
          <label htmlFor="cache-alias" className="text-sm font-medium">
            Alias (optional: every alias when empty)
          </label>
          <input
            id="cache-alias"
            name="alias"
            autoComplete="off"
            className={inputClass}
          />
        </div>
        <button
          type="submit"
          disabled={pending}
          className={secondaryButtonClass}
        >
          Clear cache
        </button>
      </div>
      {state.status === "error" && <ErrorMessage message={state.message} />}
      {state.status === "cleared" && (
        <SuccessMessage>
          {describeResult(state.removed, state.alias)}
        </SuccessMessage>
      )}
    </form>
  );
}

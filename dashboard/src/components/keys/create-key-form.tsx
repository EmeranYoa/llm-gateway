"use client";

import { useState } from "react";

import type { CreateKeyState } from "@/lib/key-actions";
import { checkNewKeyForm } from "@/lib/key-forms";

import { ErrorMessage, inputClass, primaryButtonClass } from "./form-feedback";
import { NewKeyNotice } from "./new-key-notice";
import { useCheckedAction } from "./use-checked-action";

type CreateKeyFormProps = {
  /** The `createKeyAction` server action. A prop, so tests can pass a fake one. */
  action: (state: CreateKeyState, form: FormData) => Promise<CreateKeyState>;
  /** Existing tenants, suggested in the tenant field. */
  tenants: string[];
  /** Tenant filled in at first: the selected one. */
  defaultTenant?: string;
};

const IDLE: CreateKeyState = { status: "idle" };

/** Create a key for a new or existing tenant, then show the full key once. */
export function CreateKeyForm({
  action,
  tenants,
  defaultTenant,
}: CreateKeyFormProps) {
  const { state, onSubmit, pending } = useCheckedAction<CreateKeyState>(
    action,
    IDLE,
    checkNewKeyForm,
  );
  // The id of the key whose notice the operator closed.
  const [dismissedId, setDismissedId] = useState<number | null>(null);

  const createdKey =
    state.status === "created" && state.key.id !== dismissedId
      ? state.key
      : null;

  return (
    <div className="flex flex-col gap-4">
      <form
        onSubmit={onSubmit}
        noValidate
        className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="new-key-tenant" className="text-sm font-medium">
            Tenant
          </label>
          <input
            id="new-key-tenant"
            name="tenant"
            required
            list="known-tenants"
            defaultValue={defaultTenant}
            autoComplete="off"
            className={inputClass}
          />
          <datalist id="known-tenants">
            {tenants.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-key-rpm" className="text-sm font-medium">
            Requests per minute (optional)
          </label>
          <input
            id="new-key-rpm"
            name="rpm"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-key-tokens" className="text-sm font-medium">
            Tokens per day (optional)
          </label>
          <input
            id="new-key-tokens"
            name="tokens_per_day"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            className={inputClass}
          />
        </div>
        <button type="submit" disabled={pending} className={primaryButtonClass}>
          Create key
        </button>
      </form>
      <p className="text-xs text-slate-600">
        A new tenant is created with its first key. Limits given become the
        tenant&apos;s own limits; limits left empty keep their value.
      </p>
      {state.status === "error" && <ErrorMessage message={state.message} />}
      {createdKey && (
        <NewKeyNotice
          key={createdKey.id}
          createdKey={createdKey}
          onDismiss={() => setDismissedId(createdKey.id)}
        />
      )}
    </div>
  );
}

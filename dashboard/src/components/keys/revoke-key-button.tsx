"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { RevokeKeyState } from "@/lib/key-actions";
import { checkRevokeForm } from "@/lib/key-forms";

import {
  dangerButtonClass,
  ErrorMessage,
  secondaryButtonClass,
} from "./form-feedback";
import { useCheckedAction } from "./use-checked-action";

type RevokeKeyButtonProps = {
  /** The `revokeKeyAction` server action. A prop, so tests can pass a fake one. */
  action: (state: RevokeKeyState, form: FormData) => Promise<RevokeKeyState>;
  keyId: number;
  prefix: string;
};

const IDLE: RevokeKeyState = { status: "idle" };

/**
 * Revoke a key, after a confirmation step.
 *
 * The confirmation opens in place, takes the focus (on "Cancel", the safe
 * choice) and closes with Escape, giving the focus back to the "Revoke" button.
 */
export function RevokeKeyButton({
  action,
  keyId,
  prefix,
}: RevokeKeyButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const { state, onSubmit, pending } = useCheckedAction<RevokeKeyState>(
    action,
    IDLE,
    checkRevokeForm,
  );
  const openButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  useEffect(() => {
    if (confirming) {
      cancelButton.current?.focus();
    } else if (wasConfirming.current) {
      openButton.current?.focus();
    }
    wasConfirming.current = confirming;
  }, [confirming]);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape" && !pending) {
      setConfirming(false);
    }
  }

  if (!confirming) {
    return (
      <button
        ref={openButton}
        type="button"
        onClick={() => setConfirming(true)}
        aria-label={`Revoke key ${prefix}`}
        className={secondaryButtonClass}
      >
        Revoke
      </button>
    );
  }

  const titleId = `revoke-title-${keyId}`;
  const descriptionId = `revoke-description-${keyId}`;
  return (
    <div
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={onKeyDown}
      className="flex flex-col gap-2 rounded border border-red-200 bg-red-50 p-3 text-left"
    >
      <p id={titleId} className="text-sm font-semibold text-red-900">
        Revoke key {prefix}?
      </p>
      <p id={descriptionId} className="text-sm text-red-900">
        Applications using it are refused within 60 seconds. This cannot be
        undone.
      </p>
      <form onSubmit={onSubmit} className="flex flex-wrap gap-2">
        <input type="hidden" name="keyId" value={keyId} />
        <button type="submit" disabled={pending} className={dangerButtonClass}>
          Revoke key
        </button>
        <button
          ref={cancelButton}
          type="button"
          disabled={pending}
          onClick={() => setConfirming(false)}
          className={secondaryButtonClass}
        >
          Cancel
        </button>
      </form>
      {state.status === "error" && <ErrorMessage message={state.message} />}
    </div>
  );
}

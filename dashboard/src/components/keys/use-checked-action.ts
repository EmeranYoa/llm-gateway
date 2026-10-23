import {
  type FormEvent,
  startTransition,
  useActionState,
  useCallback,
} from "react";

import type { ActionError } from "@/lib/key-actions";
import type { Checked } from "@/lib/key-forms";

type FormAction<S> = (state: S, form: FormData) => Promise<S>;

/**
 * Run a server action from a form, after checking the form in the browser.
 *
 * A form that does not pass `check` gets its error at once, without calling the
 * server. Submitting through `onSubmit` (not `<form action>`) keeps the values
 * typed in the form, so a mistake can be fixed instead of typed again.
 */
export function useCheckedAction<S>(
  action: FormAction<S | ActionError>,
  initialState: S,
  check: (form: FormData) => Checked<unknown>,
) {
  const [state, run, pending] = useActionState<S | ActionError, FormData>(
    async (previous, form) => {
      const checked = check(form);
      if (!checked.ok) {
        return { status: "error", error: checked.error };
      }
      return action(previous, form);
    },
    // S is a plain object type, never a promise: Awaited<S> is S.
    initialState as Awaited<S>,
  );

  const onSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      startTransition(() => run(form));
    },
    [run],
  );

  return { state, onSubmit, pending };
}

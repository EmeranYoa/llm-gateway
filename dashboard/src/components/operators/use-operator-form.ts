import { useEffect, useRef } from "react";

import { useAuthForm } from "@/components/auth/use-auth-form";
import type { AuthFormState, Checked } from "@/lib/auth-forms";

type FormAction<S> = (state: S, form: FormData) => Promise<S>;

/**
 * Run the server action of a form of the Operators screen, after checking the
 * form in the browser (see `useAuthForm`).
 *
 * After an error, the typed values stay and the password fields are emptied.
 * After a success, the whole form is emptied, so no password stays on screen,
 * and `onSuccess` gets the new state (a row closes its form with it).
 */
export function useOperatorForm<S extends AuthFormState>(
  action: FormAction<S>,
  initialState: S,
  check: (form: FormData) => Checked<unknown>,
  onSuccess?: (state: S) => void,
) {
  const form = useAuthForm<S>(action, initialState, check);
  const { state, formRef } = form;
  // Each answer of the action is a new state object: handle each one once.
  const handled = useRef(state);

  useEffect(() => {
    if (handled.current === state) {
      return;
    }
    handled.current = state;
    if (state.error === null) {
      formRef.current?.reset();
      onSuccess?.(state);
    }
  }, [state, formRef, onSuccess]);

  return form;
}

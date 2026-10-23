import {
  type FormEvent,
  startTransition,
  useActionState,
  useCallback,
  useRef,
} from "react";

import {
  type AuthFormState,
  type Checked,
  PASSWORD_FIELDS,
} from "@/lib/auth-forms";

type FormAction<S> = (state: S, form: FormData) => Promise<S>;

/**
 * Run the server action of a sign-in, setup, password or recovery form, after
 * checking the form in the browser.
 *
 * A form that does not pass `check` gets its error at once, without calling the
 * server. Submitting through `onSubmit` (not `<form action>`) keeps the typed
 * values when the action answers an error, so a mistake can be fixed instead
 * of typed again; the password fields are emptied, so a password never stays
 * on screen longer than needed.
 */
export function useAuthForm<S extends AuthFormState>(
  action: FormAction<S>,
  initialState: S,
  check: (form: FormData) => Checked<unknown>,
) {
  const formRef = useRef<HTMLFormElement>(null);
  const [state, run, pending] = useActionState<S, FormData>(
    async (previous, form) => {
      const checked = check(form);
      const next = checked.ok
        ? await action(previous, form)
        : { ...previous, error: checked.error };
      if (next.error !== null) {
        clearPasswords(formRef.current);
      }
      return next;
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

  return { state, onSubmit, pending, formRef };
}

function clearPasswords(form: HTMLFormElement | null): void {
  for (const name of PASSWORD_FIELDS) {
    const field = form?.elements.namedItem(name);
    if (field instanceof HTMLInputElement) {
      field.value = "";
    }
  }
}

"use client";

import { useActionState } from "react";

import type { LoginState } from "@/lib/auth-actions";

type LoginFormProps = {
  /** The `login` server action. A prop, so tests can pass a fake one. */
  action: (state: LoginState, form: FormData) => Promise<LoginState>;
  /** Information shown above the form, for example after a session has ended. */
  notice?: string;
};

const INITIAL_STATE: LoginState = { error: null };

export function LoginForm({ action, notice }: LoginFormProps) {
  const [state, formAction, pending] = useActionState(action, INITIAL_STATE);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {notice && (
        <p
          role="status"
          className="rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900"
        >
          {notice}
        </p>
      )}
      <div className="flex flex-col gap-1">
        <label htmlFor="adminKey" className="text-sm font-medium">
          Admin key
        </label>
        <input
          id="adminKey"
          name="adminKey"
          type="password"
          required
          autoComplete="off"
          spellCheck={false}
          placeholder="gwa_..."
          className="rounded border border-slate-300 px-3 py-2 font-mono text-sm focus:border-slate-500 focus:outline-none"
        />
      </div>
      {state.error && (
        <p
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {state.error}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
      >
        Sign in
      </button>
    </form>
  );
}

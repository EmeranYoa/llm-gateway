// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthFormState, RecoveryFormState } from "@/lib/auth-forms";
import { LocaleProvider } from "@/lib/i18n/client";

import { ChangePasswordForm } from "./change-password-form";
import { RecoveryForm } from "./recovery-form";
import { SetupForm } from "./setup-form";
import { SignInForm } from "./sign-in-form";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

afterEach(cleanup);

const PASSWORD = "correct horse battery";

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
}

/** The form posted to a fake action. */
function posted(action: ReturnType<typeof vi.fn>): FormData {
  return (action.mock.calls[0] as unknown as [unknown, FormData])[1];
}

function failingWith(code: string, retryAfterSeconds: number | null = null) {
  return vi.fn(async (): Promise<AuthFormState> => ({
    error: { kind: "api", code, message: "English.", retryAfterSeconds },
  }));
}

describe("SignInForm", () => {
  it("has a username and a password field", () => {
    render(<SignInForm action={vi.fn()} />);

    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "type",
      "password",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("posts the fields to the action", async () => {
    const action = failingWith("invalid_credentials");
    render(<SignInForm action={action} />);

    type("Username", "alice");
    type("Password", PASSWORD);
    submit("Sign in");

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(posted(action).get("username")).toBe("alice");
    expect(posted(action).get("password")).toBe(PASSWORD);
  });

  it("translates the error, keeps the username and empties the password", async () => {
    render(
      <LocaleProvider locale="fr">
        <SignInForm action={failingWith("invalid_credentials")} />
      </LocaleProvider>,
    );

    type("Nom d’utilisateur", "alice");
    type("Mot de passe", PASSWORD);
    submit("Se connecter");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nom d’utilisateur ou mot de passe incorrect.",
    );
    expect(screen.getByLabelText("Nom d’utilisateur")).toHaveValue("alice");
    expect(screen.getByLabelText("Mot de passe")).toHaveValue("");
  });

  it("says how long to wait after too many attempts", async () => {
    render(<SignInForm action={failingWith("too_many_attempts", 90)} />);

    type("Username", "alice");
    type("Password", PASSWORD);
    submit("Sign in");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many sign-in attempts. Try again in 1 min 30 s.",
    );
  });

  it("explains an unreachable admin API", async () => {
    render(<SignInForm action={failingWith("admin_api_unreachable")} />);

    type("Username", "alice");
    type("Password", PASSWORD);
    submit("Sign in");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The admin API cannot be reached.",
    );
  });

  it("asks for every field without calling the server", async () => {
    const action = vi.fn();
    render(<SignInForm action={action} />);

    type("Username", "alice");
    submit("Sign in");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fill in every field.",
    );
    expect(action).not.toHaveBeenCalled();
  });
});

describe("SetupForm", () => {
  function fill(password: string, again: string) {
    type("Setup token", "setup-token");
    type("Username", "alice");
    type("Password", password);
    type("Password again", again);
  }

  it("shows where to find the setup token", () => {
    render(<SetupForm action={vi.fn()} />);

    expect(screen.getByLabelText("Setup token")).toHaveAccessibleDescription(
      "Printed in the admin API logs: docker compose logs admin-api",
    );
  });

  it("refuses two different passwords without calling the server", async () => {
    const action = vi.fn();
    render(<SetupForm action={action} />);

    fill(PASSWORD, "another password");
    submit("Create the account");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords are different.",
    );
    expect(action).not.toHaveBeenCalled();
    // The token and username stay; the passwords are typed again.
    expect(screen.getByLabelText("Setup token")).toHaveValue("setup-token");
    expect(screen.getByLabelText("Username")).toHaveValue("alice");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Password again")).toHaveValue("");
  });

  it("refuses a password shorter than 12 characters, in French too", async () => {
    const action = vi.fn();
    render(
      <LocaleProvider locale="fr">
        <SetupForm action={action} />
      </LocaleProvider>,
    );

    type("Jeton de configuration", "setup-token");
    type("Nom d’utilisateur", "alice");
    type("Mot de passe", "short");
    type("Mot de passe (confirmation)", "short");
    submit("Créer le compte");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le mot de passe doit contenir au moins 12 caractères.",
    );
    expect(action).not.toHaveBeenCalled();
  });

  it("posts a valid form to the action", async () => {
    const action = vi.fn(async (): Promise<AuthFormState> => ({ error: null }));
    render(<SetupForm action={action} />);

    fill(PASSWORD, PASSWORD);
    submit("Create the account");

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const form = posted(action);
    expect(form.get("token")).toBe("setup-token");
    expect(form.get("username")).toBe("alice");
    expect(form.get("password")).toBe(PASSWORD);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("translates a wrong setup token", async () => {
    render(<SetupForm action={failingWith("invalid_setup_token")} />);

    fill(PASSWORD, PASSWORD);
    submit("Create the account");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wrong setup token.",
    );
  });
});

describe("ChangePasswordForm", () => {
  it("translates a wrong current password", async () => {
    render(
      <LocaleProvider locale="fr">
        <ChangePasswordForm action={failingWith("reauthentication_failed")} />
      </LocaleProvider>,
    );

    type("Mot de passe actuel", "old password 123");
    type("Nouveau mot de passe", PASSWORD);
    type("Nouveau mot de passe (confirmation)", PASSWORD);
    submit("Changer le mot de passe");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le mot de passe actuel est incorrect.",
    );
    expect(screen.getByLabelText("Mot de passe actuel")).toHaveValue("");
  });

  it("refuses two different new passwords without calling the server", async () => {
    const action = vi.fn();
    render(<ChangePasswordForm action={action} />);

    type("Current password", "old password 123");
    type("New password", PASSWORD);
    type("New password again", "another password");
    submit("Change the password");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords are different.",
    );
    expect(action).not.toHaveBeenCalled();
  });
});

describe("RecoveryForm", () => {
  const START: RecoveryFormState = { error: null, recoveredUsername: null };

  function fill() {
    type("Recovery token", "recovery-token");
    type("Username", "alice");
    type("New password", PASSWORD);
    type("New password again", PASSWORD);
  }

  it("says to sign in with the new password once it is set", async () => {
    const action = vi.fn(async (): Promise<RecoveryFormState> => ({
      error: null,
      recoveredUsername: "alice",
    }));
    render(<RecoveryForm action={action} />);

    fill();
    submit("Set the new password");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The password of alice is set. Sign in with it: you will then choose another one.",
    );
    expect(posted(action).get("token")).toBe("recovery-token");
    expect(posted(action).get("newPassword")).toBe(PASSWORD);
    expect(screen.queryByLabelText("Recovery token")).not.toBeInTheDocument();
  });

  it("translates the errors of the recovery", async () => {
    const action = vi.fn(async (): Promise<RecoveryFormState> => ({
      ...START,
      error: {
        kind: "api",
        code: "recovery_used",
        message: "English.",
        retryAfterSeconds: null,
      },
    }));
    render(
      <LocaleProvider locale="fr">
        <RecoveryForm action={action} />
      </LocaleProvider>,
    );

    type("Jeton de récupération", "recovery-token");
    type("Nom d’utilisateur", "alice");
    type("Nouveau mot de passe", PASSWORD);
    type("Nouveau mot de passe (confirmation)", PASSWORD);
    submit("Définir le nouveau mot de passe");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le jeton de récupération a déjà servi.",
    );
    expect(screen.getByLabelText("Jeton de récupération")).toHaveValue(
      "recovery-token",
    );
  });
});

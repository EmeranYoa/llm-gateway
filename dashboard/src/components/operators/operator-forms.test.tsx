// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";
import type {
  OperatorFormState,
  OwnPasswordFormState,
} from "@/lib/operator-forms";

import { ChangeOwnPasswordForm } from "./change-own-password-form";
import { CreateOperatorForm } from "./create-operator-form";

afterEach(cleanup);

const PASSWORD = "correct horse battery";
const MY_PASSWORD = "my current password";

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
}

function apiFailure(code: string) {
  return {
    kind: "api" as const,
    code,
    message: "English.",
    retryAfterSeconds: null,
  };
}

describe("CreateOperatorForm", () => {
  function fill() {
    type("Username", "bob");
    type("Password", PASSWORD);
    type("Password again", PASSWORD);
    type("Your current password", MY_PASSWORD);
  }

  it("says the new operator must change the password at the first sign-in", () => {
    render(<CreateOperatorForm action={vi.fn()} />);

    expect(
      screen.getByText(/must change this password at their first sign-in/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Your current password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });

  it("posts the fields, then empties the form and says it is done", async () => {
    const action = vi.fn(async (): Promise<OperatorFormState> => ({
      error: null,
      done: { username: "bob" },
    }));
    render(<CreateOperatorForm action={action} />);

    fill();
    submit("Create the account");

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const form = (action.mock.calls[0] as unknown as [unknown, FormData])[1];
    expect(Object.fromEntries(form)).toEqual({
      username: "bob",
      password: PASSWORD,
      passwordAgain: PASSWORD,
      currentPassword: MY_PASSWORD,
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Account bob created.",
    );
    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Your current password")).toHaveValue("");
  });

  it("checks the passwords in the browser first", async () => {
    const action = vi.fn();
    render(<CreateOperatorForm action={action} />);

    fill();
    type("Password again", "something else entirely");
    submit("Create the account");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords are different.",
    );
    expect(action).not.toHaveBeenCalled();
  });

  it("translates a taken username, keeps it and empties the passwords", async () => {
    const action = vi.fn(async (): Promise<OperatorFormState> => ({
      error: apiFailure("operator_exists"),
      done: null,
    }));
    render(
      <LocaleProvider locale="fr">
        <CreateOperatorForm action={action} />
      </LocaleProvider>,
    );

    type("Nom d’utilisateur", "bob");
    type("Mot de passe", PASSWORD);
    type("Mot de passe (confirmation)", PASSWORD);
    type("Votre mot de passe actuel", MY_PASSWORD);
    submit("Créer le compte");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Un compte d’opérateur porte déjà ce nom d’utilisateur.",
    );
    expect(screen.getByLabelText("Nom d’utilisateur")).toHaveValue("bob");
    expect(screen.getByLabelText("Mot de passe")).toHaveValue("");
    expect(screen.getByLabelText("Votre mot de passe actuel")).toHaveValue("");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("ChangeOwnPasswordForm", () => {
  function fill(again = PASSWORD) {
    type("Current password", MY_PASSWORD);
    type("New password", PASSWORD);
    type("New password again", again);
  }

  it("posts the current and new passwords, then says it is changed", async () => {
    const action = vi.fn(async (): Promise<OwnPasswordFormState> => ({
      error: null,
      changed: true,
    }));
    render(<ChangeOwnPasswordForm action={action} />);

    fill();
    submit("Change my password");

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const form = (action.mock.calls[0] as unknown as [unknown, FormData])[1];
    expect(form.get("currentPassword")).toBe(MY_PASSWORD);
    expect(form.get("newPassword")).toBe(PASSWORD);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your password is changed.",
    );
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("refuses a short password in the browser", async () => {
    const action = vi.fn();
    render(<ChangeOwnPasswordForm action={action} />);

    type("Current password", MY_PASSWORD);
    type("New password", "short");
    type("New password again", "short");
    submit("Change my password");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "at least 12 characters",
    );
    expect(action).not.toHaveBeenCalled();
  });

  it("shows a wrong current password and empties the fields", async () => {
    const action = vi.fn(async (): Promise<OwnPasswordFormState> => ({
      error: apiFailure("reauthentication_failed"),
      changed: false,
    }));
    render(<ChangeOwnPasswordForm action={action} />);

    fill();
    submit("Change my password");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current password is wrong.",
    );
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

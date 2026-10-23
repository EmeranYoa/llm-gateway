// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";
import type { Operator, OperatorFormState } from "@/lib/operator-forms";

import type { OperatorFormAction } from "./account-panel";
import { OperatorsTable } from "./operators-table";

afterEach(cleanup);

const PASSWORD = "correct horse battery";
const MY_PASSWORD = "my current password";

const ALICE: Operator = {
  id: 1,
  username: "alice",
  enabled: true,
  must_change_password: false,
  created_at: "2026-10-01T08:00:00Z",
  last_sign_in_at: "2026-10-23T09:30:00Z",
};
const BOB: Operator = {
  id: 2,
  username: "bob",
  enabled: true,
  must_change_password: true,
  created_at: "2026-10-20T08:00:00Z",
  last_sign_in_at: null,
};
const CAROL: Operator = {
  id: 3,
  username: "carol",
  enabled: false,
  must_change_password: false,
  created_at: "2026-10-02T08:00:00Z",
  last_sign_in_at: "2026-10-10T17:00:00Z",
};

function fakeAction(result: OperatorFormState) {
  return vi.fn<OperatorFormAction>(async () => result);
}

function failingWith(code: string) {
  return fakeAction({
    error: { kind: "api", code, message: "English.", retryAfterSeconds: null },
    done: null,
  });
}

function succeeding(username: string) {
  return fakeAction({ error: null, done: { username } });
}

function renderTable({
  operators = [ALICE, BOB, CAROL],
  currentUsername = "alice" as string | null,
  reset = succeeding("bob"),
  disable = succeeding("bob"),
  enable = succeeding("carol"),
  locale = "en" as "en" | "fr",
} = {}) {
  render(
    <LocaleProvider locale={locale}>
      <OperatorsTable
        operators={operators}
        currentUsername={currentUsername}
        actions={{ reset, disable, enable }}
      />
    </LocaleProvider>,
  );
  return { reset, disable, enable };
}

function row(username: string) {
  return screen.getByRole("rowheader", { name: new RegExp(username) })
    .parentElement as HTMLElement;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** The form posted to a fake action. */
function posted(action: ReturnType<typeof fakeAction>): FormData {
  return action.mock.calls[0][1];
}

describe("OperatorsTable: the list", () => {
  it("marks you, the disabled accounts and the passwords to change", () => {
    renderTable();

    expect(within(row("alice")).getByText("you")).toBeInTheDocument();
    expect(within(row("alice")).getByText("Enabled")).toBeInTheDocument();
    expect(within(row("bob")).queryByText("you")).not.toBeInTheDocument();
    expect(
      within(row("bob")).getByText("Must change password"),
    ).toBeInTheDocument();
    expect(within(row("bob")).getByText("never")).toBeInTheDocument();
    expect(within(row("carol")).getByText("Disabled")).toBeInTheDocument();
    expect(within(row("carol")).getByText("Disabled")).toHaveAttribute(
      "title",
      "Cannot sign in until the account is enabled again.",
    );
  });

  it("shows the last sign-in as a time", () => {
    renderTable();

    expect(
      within(row("alice")).getByText(
        (_, element) => element?.tagName === "TIME",
      ),
    ).toHaveAttribute("datetime", "2026-10-23T09:30:00Z");
  });

  it("speaks French", () => {
    renderTable({ locale: "fr" });

    expect(within(row("alice")).getByText("vous")).toBeInTheDocument();
    expect(within(row("carol")).getByText("Désactivé")).toBeInTheDocument();
    expect(
      within(row("bob")).getByText("Doit changer de mot de passe"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Désactiver bob" }),
    ).toBeInTheDocument();
  });

  it("offers no action on your own account", () => {
    renderTable();

    expect(within(row("alice")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers reset and disable on an enabled account, reset and enable on a disabled one", () => {
    renderTable();

    expect(
      within(row("bob"))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Reset password", "Disable"]);
    expect(
      within(row("carol"))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Reset password", "Enable"]);
  });

  it("hides disable for the last enabled account", () => {
    renderTable({ operators: [BOB, CAROL], currentUsername: null });

    expect(
      screen.queryByRole("button", { name: "Disable bob" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reset the password of bob" }),
    ).toBeInTheDocument();
  });
});

describe("OperatorsTable: disable", () => {
  it("asks for confirmation and the current password before disabling", async () => {
    const { disable } = renderTable();

    fireEvent.click(screen.getByRole("button", { name: "Disable bob" }));
    const dialog = screen.getByRole("alertdialog", { name: "Disable bob?" });

    expect(dialog).toHaveTextContent("their open sessions are closed at once");
    expect(
      within(dialog).getByLabelText("Your current password"),
    ).toHaveFocus();
    expect(disable).not.toHaveBeenCalled();

    type("Your current password", MY_PASSWORD);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Disable the account" }),
    );

    await waitFor(() => expect(disable).toHaveBeenCalledTimes(1));
    expect(posted(disable).get("operatorId")).toBe("2");
    expect(posted(disable).get("currentPassword")).toBe(MY_PASSWORD);
  });

  it("closes the confirmation and says what changed after a success", async () => {
    renderTable();

    fireEvent.click(screen.getByRole("button", { name: "Disable bob" }));
    type("Your current password", MY_PASSWORD);
    fireEvent.click(
      screen.getByRole("button", { name: "Disable the account" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "bob is disabled.",
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks for the current password without calling the server", async () => {
    const { disable } = renderTable();

    fireEvent.click(screen.getByRole("button", { name: "Disable bob" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Disable the account" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fill in every field.",
    );
    expect(disable).not.toHaveBeenCalled();
  });

  it("shows the guard of the admin API, translated, and empties the password", async () => {
    renderTable({
      disable: failingWith("last_enabled_operator"),
      locale: "fr",
    });

    fireEvent.click(screen.getByRole("button", { name: "Désactiver bob" }));
    type("Votre mot de passe actuel", MY_PASSWORD);
    fireEvent.click(
      screen.getByRole("button", { name: "Désactiver le compte" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "C’est le dernier compte actif",
    );
    expect(screen.getByLabelText("Votre mot de passe actuel")).toHaveValue("");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("closes with Cancel or Escape without disabling, and gives the focus back", () => {
    const { disable } = renderTable();

    const open = screen.getByRole("button", { name: "Disable bob" });
    fireEvent.click(open);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(open).toHaveFocus();

    fireEvent.click(open);
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(disable).not.toHaveBeenCalled();
  });
});

describe("OperatorsTable: reset password", () => {
  function openReset() {
    fireEvent.click(
      screen.getByRole("button", { name: "Reset the password of bob" }),
    );
    return screen.getByRole("group", { name: "New password for bob" });
  }

  it("posts the new password and the current one", async () => {
    const { reset } = renderTable();

    openReset();
    type("New password", PASSWORD);
    type("New password again", PASSWORD);
    type("Your current password", MY_PASSWORD);
    fireEvent.click(screen.getByRole("button", { name: "Reset the password" }));

    await waitFor(() => expect(reset).toHaveBeenCalledTimes(1));
    expect(posted(reset).get("operatorId")).toBe("2");
    expect(posted(reset).get("password")).toBe(PASSWORD);
    expect(posted(reset).get("currentPassword")).toBe(MY_PASSWORD);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The password of bob is reset.",
    );
  });

  it("checks that both new passwords match before calling the server", async () => {
    const { reset } = renderTable();

    openReset();
    type("New password", PASSWORD);
    type("New password again", `${PASSWORD}?`);
    type("Your current password", MY_PASSWORD);
    fireEvent.click(screen.getByRole("button", { name: "Reset the password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords are different.",
    );
    expect(reset).not.toHaveBeenCalled();
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("shows a wrong current password", async () => {
    renderTable({ reset: failingWith("reauthentication_failed") });

    openReset();
    type("New password", PASSWORD);
    type("New password again", PASSWORD);
    type("Your current password", "wrong password");
    fireEvent.click(screen.getByRole("button", { name: "Reset the password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current password is wrong.",
    );
  });
});

describe("OperatorsTable: enable", () => {
  it("enables a disabled account with the current password", async () => {
    const { enable } = renderTable();

    fireEvent.click(screen.getByRole("button", { name: "Enable carol" }));
    const panel = screen.getByRole("group", { name: "Enable carol" });
    expect(panel).toHaveTextContent(
      "They can sign in again with their password.",
    );
    type("Your current password", MY_PASSWORD);
    fireEvent.click(screen.getByRole("button", { name: "Enable the account" }));

    await waitFor(() => expect(enable).toHaveBeenCalledTimes(1));
    expect(posted(enable).get("operatorId")).toBe("3");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "carol is enabled.",
    );
  });
});

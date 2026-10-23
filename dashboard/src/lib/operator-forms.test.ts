import { describe, expect, it } from "vitest";

import {
  checkNewOperatorForm,
  checkPasswordResetForm,
  checkReauthenticationForm,
  type Operator,
  operatorActions,
} from "./operator-forms";

const PASSWORD = "correct horse battery";

function formOf(fields: Record<string, string>): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    form.set(name, value);
  }
  return form;
}

function operator(
  username: string,
  enabled = true,
  id = username.length,
): Operator {
  return {
    id,
    username,
    enabled,
    must_change_password: false,
    created_at: "2026-10-20T08:00:00Z",
    last_sign_in_at: null,
  };
}

describe("checkNewOperatorForm", () => {
  const fields = {
    username: " bob ",
    password: PASSWORD,
    passwordAgain: PASSWORD,
    currentPassword: "mine",
  };

  it("trims the username, never the passwords", () => {
    expect(
      checkNewOperatorForm(formOf({ ...fields, currentPassword: " mine " })),
    ).toEqual({
      ok: true,
      value: {
        username: "bob",
        password: PASSWORD,
        current_password: " mine ",
      },
    });
  });

  it.each([
    [{ username: " " }, "missingFields"],
    [{ currentPassword: "" }, "missingFields"],
    [{ passwordAgain: "" }, "missingFields"],
    [{ passwordAgain: `${PASSWORD}!` }, "passwordsDiffer"],
    [{ password: "too short", passwordAgain: "too short" }, "passwordTooShort"],
  ])("refuses %o (%s)", (change, problem) => {
    expect(checkNewOperatorForm(formOf({ ...fields, ...change }))).toEqual({
      ok: false,
      error: { kind: "form", problem },
    });
  });
});

describe("checkPasswordResetForm", () => {
  it("reads the account id, the new password and the current one", () => {
    const form = formOf({
      operatorId: "12",
      password: PASSWORD,
      passwordAgain: PASSWORD,
      currentPassword: "mine",
    });

    expect(checkPasswordResetForm(form)).toEqual({
      ok: true,
      value: {
        operatorId: 12,
        request: { password: PASSWORD, current_password: "mine" },
      },
    });
  });
});

describe("checkReauthenticationForm", () => {
  it("reads the account id and the current password", () => {
    expect(
      checkReauthenticationForm(
        formOf({ operatorId: "3", currentPassword: "mine" }),
      ),
    ).toEqual({
      ok: true,
      value: { operatorId: 3, request: { current_password: "mine" } },
    });
  });

  it.each(["", "-1", "1.5", "7/disable"])("refuses the id %j", (id) => {
    expect(
      checkReauthenticationForm(
        formOf({ operatorId: id, currentPassword: "mine" }),
      ).ok,
    ).toBe(false);
  });
});

describe("operatorActions", () => {
  it("offers nothing on your own account", () => {
    const me = operator("alice");
    const others = [me, operator("bob")];

    expect(operatorActions(me, "alice", others)).toEqual([]);
  });

  it("offers a reset and a disable on another enabled account", () => {
    const bob = operator("bob");

    expect(operatorActions(bob, "alice", [operator("alice"), bob])).toEqual([
      "reset",
      "disable",
    ]);
  });

  it("offers a reset and an enable on a disabled account", () => {
    const bob = operator("bob", false);

    expect(operatorActions(bob, "alice", [operator("alice"), bob])).toEqual([
      "reset",
      "enable",
    ]);
  });

  it("hides disable for the last enabled account", () => {
    const bob = operator("bob");
    const list = [operator("alice", false), bob];

    // The signed-in account is unknown: the last enabled one stays enabled.
    expect(operatorActions(bob, null, list)).toEqual(["reset"]);
  });
});

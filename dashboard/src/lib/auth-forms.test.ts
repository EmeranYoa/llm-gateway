import { describe, expect, it } from "vitest";

import {
  checkPasswordChangeForm,
  checkRecoveryForm,
  checkSetupForm,
  checkSignInForm,
} from "./auth-forms";

function formOf(fields: Record<string, string>): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    form.set(name, value);
  }
  return form;
}

const PASSWORD = "twelve chars";

describe("checkSignInForm", () => {
  it("trims the username, never the password", () => {
    expect(
      checkSignInForm(formOf({ username: " alice ", password: " secret " })),
    ).toEqual({
      ok: true,
      value: { username: "alice", password: " secret " },
    });
  });

  it("needs both fields", () => {
    expect(checkSignInForm(formOf({ username: "  ", password: "x" }))).toEqual({
      ok: false,
      error: { kind: "form", problem: "missingFields" },
    });
  });
});

describe("checkSetupForm", () => {
  const setup = {
    token: "token",
    username: "alice",
    password: PASSWORD,
    passwordAgain: PASSWORD,
  };

  it("accepts a password of exactly 12 characters typed twice", () => {
    expect(checkSetupForm(formOf(setup))).toEqual({
      ok: true,
      value: { token: "token", username: "alice", password: PASSWORD },
    });
  });

  it("finds each problem", () => {
    const problem = (fields: Record<string, string>) => {
      const checked = checkSetupForm(formOf({ ...setup, ...fields }));
      return checked.ok ? null : checked.error;
    };

    expect(problem({ token: "" })).toMatchObject({ problem: "missingFields" });
    expect(problem({ passwordAgain: "" })).toMatchObject({
      problem: "missingFields",
    });
    expect(problem({ passwordAgain: "twelve charz" })).toMatchObject({
      problem: "passwordsDiffer",
    });
    expect(
      problem({ password: "eleven char", passwordAgain: "eleven char" }),
    ).toMatchObject({ problem: "passwordTooShort" });
  });

  it("counts characters, not UTF-16 units", () => {
    // 11 characters, 22 UTF-16 units.
    const emoji = "😀".repeat(11);

    expect(
      checkSetupForm(
        formOf({ ...setup, password: emoji, passwordAgain: emoji }),
      ),
    ).toMatchObject({ ok: false, error: { problem: "passwordTooShort" } });
  });
});

describe("checkPasswordChangeForm", () => {
  it("builds the body of the admin API", () => {
    expect(
      checkPasswordChangeForm(
        formOf({
          currentPassword: "old",
          newPassword: PASSWORD,
          newPasswordAgain: PASSWORD,
        }),
      ),
    ).toEqual({
      ok: true,
      value: { current_password: "old", new_password: PASSWORD },
    });
  });

  it("needs the current password", () => {
    expect(
      checkPasswordChangeForm(
        formOf({ newPassword: PASSWORD, newPasswordAgain: PASSWORD }),
      ),
    ).toMatchObject({ ok: false, error: { problem: "missingFields" } });
  });
});

describe("checkRecoveryForm", () => {
  it("builds the body of the admin API", () => {
    expect(
      checkRecoveryForm(
        formOf({
          token: " token ",
          username: "alice",
          newPassword: PASSWORD,
          newPasswordAgain: PASSWORD,
        }),
      ),
    ).toEqual({
      ok: true,
      value: { token: "token", username: "alice", new_password: PASSWORD },
    });
  });
});

import { describe, expect, it } from "vitest";

import { describeAuthError } from "./auth-errors";

const NBSP = " ";

function apiError(
  code: string | null,
  retryAfterSeconds: number | null = null,
) {
  return {
    kind: "api" as const,
    code,
    message: "English message of the admin API.",
    retryAfterSeconds,
  };
}

describe("describeAuthError", () => {
  it("translates the checks of the form", () => {
    const error = {
      kind: "form" as const,
      problem: "passwordsDiffer" as const,
    };

    expect(describeAuthError(error, "en").message).toBe(
      "The two passwords are different.",
    );
    expect(describeAuthError(error, "fr").message).toBe(
      "Les deux mots de passe sont différents.",
    );
  });

  it("translates the sign-in errors by code", () => {
    expect(describeAuthError(apiError("invalid_credentials"), "en")).toEqual({
      message: "Wrong username or password.",
      detail: null,
    });
    expect(
      describeAuthError(apiError("invalid_credentials"), "fr").message,
    ).toBe("Nom d’utilisateur ou mot de passe incorrect.");
    expect(
      describeAuthError(apiError("authentication_unavailable"), "en").message,
    ).toBe("Sign-in cannot be checked right now. Try again later.");
    expect(
      describeAuthError(apiError("admin_api_unreachable"), "en").message,
    ).toBe("The admin API cannot be reached. Check that it is running.");
  });

  it("says how long to wait after too many attempts", () => {
    expect(
      describeAuthError(apiError("too_many_attempts", 42), "en").message,
    ).toBe("Too many sign-in attempts. Try again in 42 s.");
    expect(
      describeAuthError(apiError("too_many_attempts", 900), "fr").message,
    ).toBe(`Trop de tentatives de connexion. Réessayez dans 15${NBSP}min.`);
  });

  it("still explains too many attempts without a wait time", () => {
    expect(describeAuthError(apiError("too_many_attempts"), "en").message).toBe(
      "Too many sign-in attempts. Try again later.",
    );
  });

  it("keeps the English detail of an unknown code", () => {
    expect(describeAuthError(apiError("brand_new"), "en").detail).toBe(
      "Details: English message of the admin API.",
    );
  });
});

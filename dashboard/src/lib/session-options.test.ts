import { describe, expect, it } from "vitest";

import {
  SESSION_MAX_AGE_SECONDS,
  buildSessionOptions,
} from "./session-options";

describe("buildSessionOptions", () => {
  it("refuses a missing secret", () => {
    expect(() => buildSessionOptions(undefined)).toThrow(
      /DASHBOARD_SESSION_SECRET is missing/,
    );
  });

  it("refuses a secret shorter than 32 characters", () => {
    expect(() => buildSessionOptions("too-short")).toThrow(
      /at least 32 characters/,
    );
  });

  it("encrypts the cookie with the secret", () => {
    const secret = "x".repeat(32);

    expect(buildSessionOptions(secret).password).toBe(secret);
  });

  it("keeps the cookie away from scripts and other sites, for 8 hours", () => {
    const options = buildSessionOptions("x".repeat(32));

    expect(SESSION_MAX_AGE_SECONDS).toBe(8 * 60 * 60);
    expect(options.ttl).toBe(SESSION_MAX_AGE_SECONDS);
    expect(options.cookieOptions).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "strict",
      path: "/",
      maxAge: SESSION_MAX_AGE_SECONDS,
    });
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadAccount } from "@/lib/account";
import { SESSION_COOKIE_NAME } from "@/lib/session-options";

import { getI18n } from "./server";

const request = vi.hoisted(() => ({
  cookies: {} as Record<string, string>,
  acceptLanguage: null as string | null,
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name in request.cookies
        ? { name, value: request.cookies[name] }
        : undefined,
  }),
  headers: async () =>
    new Headers(
      request.acceptLanguage === null
        ? {}
        : { "accept-language": request.acceptLanguage },
    ),
}));

vi.mock("@/lib/account", () => ({ loadAccount: vi.fn() }));

function signedInAs(language: string | null) {
  request.cookies[SESSION_COOKIE_NAME] = "sealed-session";
  vi.mocked(loadAccount).mockResolvedValue({
    status: "signed-in",
    me: { username: "alice", must_change_password: false, language },
  });
}

beforeEach(() => {
  request.cookies = {};
  request.acceptLanguage = null;
  vi.mocked(loadAccount).mockReset();
});

describe("getI18n", () => {
  it("reads the language of the request and gives its translator", async () => {
    request.acceptLanguage = "fr-CA,fr;q=0.9,en;q=0.8";

    const { locale, t } = await getI18n();

    expect(locale).toBe("fr");
    expect(t("nav.signOut")).toBe("Se déconnecter");
  });

  it("lets the lang cookie win over Accept-Language", async () => {
    request.cookies.lang = "en";
    request.acceptLanguage = "fr";

    expect((await getI18n()).locale).toBe("en");
  });

  it("never asks the admin API without a session cookie", async () => {
    request.acceptLanguage = "fr";

    await getI18n();

    expect(loadAccount).not.toHaveBeenCalled();
  });

  it("lets the language of the account win over the cookie and the header", async () => {
    request.cookies.lang = "en";
    request.acceptLanguage = "en";
    signedInAs("fr");

    expect((await getI18n()).locale).toBe("fr");
  });

  it("falls back to the cookie when the account has no language", async () => {
    request.cookies.lang = "fr";
    signedInAs(null);

    expect((await getI18n()).locale).toBe("fr");
  });

  it("falls back to the cookie when the account cannot be read", async () => {
    request.cookies.lang = "fr";
    request.cookies[SESSION_COOKIE_NAME] = "sealed-session";
    vi.mocked(loadAccount).mockResolvedValue({ status: "expired" });

    expect((await getI18n()).locale).toBe("fr");
  });
});

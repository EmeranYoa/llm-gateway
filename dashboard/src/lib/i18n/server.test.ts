import { describe, expect, it, vi } from "vitest";

import { getI18n } from "./server";

const request = vi.hoisted(() => ({
  cookie: undefined as string | undefined,
  acceptLanguage: null as string | null,
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "lang" && request.cookie !== undefined
        ? { name, value: request.cookie }
        : undefined,
  }),
  headers: async () =>
    new Headers(
      request.acceptLanguage === null
        ? {}
        : { "accept-language": request.acceptLanguage },
    ),
}));

describe("getI18n", () => {
  it("reads the language of the request and gives its translator", async () => {
    request.cookie = undefined;
    request.acceptLanguage = "fr-CA,fr;q=0.9,en;q=0.8";

    const { locale, t } = await getI18n();

    expect(locale).toBe("fr");
    expect(t("nav.signOut")).toBe("Se déconnecter");
  });

  it("lets the lang cookie win over Accept-Language", async () => {
    request.cookie = "en";
    request.acceptLanguage = "fr";

    expect((await getI18n()).locale).toBe("en");
  });
});

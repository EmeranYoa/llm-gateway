import { describe, expect, it } from "vitest";

import {
  localeCookie,
  localeFromAcceptLanguage,
  resolveLocale,
} from "./locale";

describe("resolveLocale", () => {
  it("is English without any choice", () => {
    expect(resolveLocale(undefined, null)).toBe("en");
    expect(resolveLocale(null, "")).toBe("en");
  });

  it("follows the browser's Accept-Language header", () => {
    expect(resolveLocale(undefined, "fr-CA,fr;q=0.9,en;q=0.8")).toBe("fr");
    expect(resolveLocale(undefined, "en-GB,en;q=0.9,fr;q=0.8")).toBe("en");
  });

  it("lets the cookie of the language selector win over the header", () => {
    expect(resolveLocale("en", "fr-FR,fr;q=0.9")).toBe("en");
    expect(resolveLocale("fr", "en-US")).toBe("fr");
  });

  it("ignores a cookie with an unsupported value", () => {
    expect(resolveLocale("de", "fr")).toBe("fr");
    expect(resolveLocale("", "fr")).toBe("fr");
  });

  it("lets the language of the account win over everything", () => {
    expect(resolveLocale("en", "en", "fr")).toBe("fr");
    expect(resolveLocale("fr", "fr", null)).toBe("fr");
    expect(resolveLocale("fr", "fr", "de")).toBe("fr");
  });

  it("falls back to English when no language is supported", () => {
    expect(resolveLocale(undefined, "de-DE,de;q=0.9,es;q=0.8")).toBe("en");
    expect(resolveLocale(undefined, "*")).toBe("en");
    expect(resolveLocale(undefined, "not a header;;;")).toBe("en");
  });
});

describe("localeFromAcceptLanguage", () => {
  it("takes the supported language with the highest weight", () => {
    expect(localeFromAcceptLanguage("de;q=0.9,en;q=0.5,fr;q=0.7")).toBe("fr");
    expect(localeFromAcceptLanguage("en;q=0.2, FR-be")).toBe("fr");
  });

  it("keeps the order of the header for equal weights", () => {
    expect(localeFromAcceptLanguage("fr,en")).toBe("fr");
    expect(localeFromAcceptLanguage("en,fr")).toBe("en");
  });

  it("skips languages refused with q=0", () => {
    expect(localeFromAcceptLanguage("fr;q=0,en;q=0.1")).toBe("en");
  });

  it("gives null when no language is supported", () => {
    expect(localeFromAcceptLanguage("de,es")).toBeNull();
  });
});

describe("localeCookie", () => {
  it("keeps the language for one year on the whole dashboard", () => {
    expect(localeCookie("fr", false)).toBe(
      "lang=fr; Path=/; Max-Age=31536000; SameSite=Lax",
    );
  });

  it("is Secure on HTTPS", () => {
    expect(localeCookie("en", true)).toBe(
      "lang=en; Path=/; Max-Age=31536000; SameSite=Lax; Secure",
    );
  });
});

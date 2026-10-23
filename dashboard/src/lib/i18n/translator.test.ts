import { describe, expect, it } from "vitest";

import { createTranslator, getTranslator } from "./translator";

/** A small dictionary, to test plurals and placeholders apart from the real texts. */
const testMessages = {
  greeting: "Hello {name}",
  requests: { one: "{count} request", other: "{count} requests" },
  nested: { cost: "{amount} for {count} calls" },
  tokens: {
    one: "{count} token for {tenant}",
    other: "{count} tokens for {tenant}",
  },
} as const;

const testFrench = {
  greeting: "Bonjour {name}",
  requests: { one: "{count} requête", other: "{count} requêtes" },
  nested: { cost: "{amount} pour {count} appels" },
  tokens: {
    one: "{count} jeton pour {tenant}",
    other: "{count} jetons pour {tenant}",
  },
};

const english = createTranslator<typeof testMessages>("en", testMessages);
const french = createTranslator<typeof testMessages>("fr", testFrench);

const NNBSP = " ";

describe("t()", () => {
  it("reads a message of the dashboard by its dotted key", () => {
    expect(getTranslator("en")("nav.overview")).toBe("Overview");
    expect(getTranslator("fr")("nav.overview")).toBe("Vue d’ensemble");
  });

  it("fills the placeholders", () => {
    expect(english("greeting", { name: "Ada" })).toBe("Hello Ada");
    expect(french("greeting", { name: "Ada" })).toBe("Bonjour Ada");
    expect(
      getTranslator("fr")("apiError.englishDetail", { detail: "Boom." }),
    ).toBe("Détail (en anglais) : Boom.");
  });

  it("writes numbers in the format of the language", () => {
    expect(english("nested.cost", { amount: "$2.50", count: 1250.5 })).toBe(
      "$2.50 for 1,250.5 calls",
    );
    expect(french("nested.cost", { amount: "2,50 $", count: 1250.5 })).toBe(
      `2,50 $ pour 1${NNBSP}250,5 appels`,
    );
  });

  it("chooses the plural form with the rules of each language", () => {
    expect(english("requests", { count: 0 })).toBe("0 requests");
    expect(english("requests", { count: 1 })).toBe("1 request");
    expect(english("requests", { count: 2 })).toBe("2 requests");
    // In French, 0 and 1 take the singular.
    expect(french("requests", { count: 0 })).toBe("0 requête");
    expect(french("requests", { count: 1 })).toBe("1 requête");
    expect(french("requests", { count: 1250 })).toBe(`1${NNBSP}250 requêtes`);
  });

  it("falls back to `other` when a plural form is missing", () => {
    // French has a `many` form for millions; the dictionary only has `other`.
    expect(french("requests", { count: 1_000_000 })).toBe(
      `1${NNBSP}000${NNBSP}000 requêtes`,
    );
  });

  it("fills the other placeholders of a plural message", () => {
    expect(french("tokens", { count: 1, tenant: "acme" })).toBe(
      "1 jeton pour acme",
    );
  });

  it("checks keys and values at compile time", () => {
    // @ts-expect-error: unknown key.
    expect(english("nope")).toBe("nope");
    // @ts-expect-error: `{name}` needs a value.
    expect(english("greeting")).toBe("Hello {name}");
    // @ts-expect-error: a plural message needs `count`.
    expect(english("requests", {})).toBe("{count} requests");
    // @ts-expect-error: a group is not a message.
    expect(english("nested")).toBe("nested");
  });
});

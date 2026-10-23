import { describe, expect, it } from "vitest";

import { describeKeyError } from "./key-errors";

// French texts below have a no-break space before ":", as in `messages/fr.ts`.

describe("describeKeyError", () => {
  it("translates a check of the form, with the name of the field", () => {
    const error = {
      kind: "form",
      problem: "notWholeNumber",
      field: "tokens_per_day",
    } as const;

    expect(describeKeyError(error, "en")).toEqual({
      message: "Tokens per day must be a whole number greater than 0.",
      detail: null,
    });
    expect(describeKeyError(error, "fr").message).toBe(
      "Tokens par jour : saisissez un nombre entier supérieur à 0.",
    );
  });

  it("translates an error of the admin API from its code", () => {
    const error = {
      kind: "api",
      status: 409,
      code: "key_already_revoked",
      message: "API key 7 is already revoked.",
    } as const;

    expect(describeKeyError(error, "fr")).toEqual({
      message: "Cette clé d’API est déjà révoquée.",
      detail: null,
    });
  });

  it("says the values were refused, with the English detail, for a 400 without a code", () => {
    const error = {
      kind: "api",
      status: 400,
      code: null,
      message: "Invalid value for 'rpm'.",
    } as const;

    expect(describeKeyError(error, "en")).toEqual({
      message: "The admin API refused the values.",
      detail: "Details: Invalid value for 'rpm'.",
    });
  });

  it("gives the HTTP status of any other error", () => {
    const error = {
      kind: "api",
      status: 500,
      code: null,
      message: "Internal error.",
    } as const;

    expect(describeKeyError(error, "fr")).toEqual({
      message: "L’API d’administration a renvoyé une erreur (HTTP 500).",
      detail: "Détail (en anglais) : Internal error.",
    });
  });
});

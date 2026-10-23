import { describe, expect, it } from "vitest";

import { describeApiError } from "./api-errors";

describe("describeApiError", () => {
  it("translates a known error code", () => {
    const error = { code: "tenant_not_found", message: "Unknown tenant 'x'." };

    expect(describeApiError(error, "en")).toEqual({
      message: "This tenant does not exist.",
      detail: null,
    });
    expect(describeApiError(error, "fr")).toEqual({
      message: "Ce tenant n’existe pas.",
      detail: null,
    });
  });

  it("shows a generic message and the English detail for an unknown code", () => {
    const error = { code: "brand_new_code", message: "Something broke." };

    expect(describeApiError(error, "en")).toEqual({
      message: "The admin API could not complete the request.",
      detail: "Details: Something broke.",
    });
    expect(describeApiError(error, "fr")).toEqual({
      message: "L’API d’administration n’a pas pu traiter la demande.",
      detail: "Détail (en anglais) : Something broke.",
    });
  });

  it("treats an error without a code as unknown", () => {
    const error = { code: null, message: "Invalid value for 'period'." };

    expect(describeApiError(error, "fr").detail).toContain(
      "Invalid value for 'period'.",
    );
  });

  it("never mistakes an inherited property for a code", () => {
    const error = { code: "toString", message: "Odd." };

    expect(describeApiError(error, "en").detail).toBe("Details: Odd.");
  });
});

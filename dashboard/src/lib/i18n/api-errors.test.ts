import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { en } from "@/messages/en";
import { fr } from "@/messages/fr";

import {
  ADMIN_API_ERROR_CODES,
  DASHBOARD_ERROR_CODES,
} from "./api-error-codes";
import { describeApiError } from "./api-errors";

/** The Python package of the admin API, in a clone of the repository. */
const ADMIN_API_SOURCES = fileURLToPath(
  new URL("../../../../app/admin_api", import.meta.url),
);

/** Every `code="..."` passed to an error response by the admin API. */
function codesOfAdminApiSources(): string[] {
  const codes = new Set<string>();
  for (const file of readdirSync(ADMIN_API_SOURCES)) {
    if (file.endsWith(".py")) {
      const source = readFileSync(join(ADMIN_API_SOURCES, file), "utf8");
      for (const match of source.matchAll(/code="([a-z_]+)"/g)) {
        codes.add(match[1]);
      }
    }
  }
  return [...codes].sort();
}

describe("error codes of the admin API", () => {
  it.each([
    ["English", en],
    ["French", fr],
  ])("each have a message in %s", (_, messages) => {
    const codes: Record<string, string> = messages.apiError.codes;
    for (const code of ADMIN_API_ERROR_CODES) {
      expect(codes[code]?.trim(), code).toBeTruthy();
    }
  });

  it("have no message for a code that is not in the list", () => {
    expect(Object.keys(en.apiError.codes).sort()).toEqual(
      [...ADMIN_API_ERROR_CODES].sort(),
    );
  });

  it.skipIf(!existsSync(ADMIN_API_SOURCES))(
    "are the codes returned by the Python sources of the admin API",
    () => {
      const fromDashboard = new Set(DASHBOARD_ERROR_CODES);
      expect(codesOfAdminApiSources()).toEqual(
        ADMIN_API_ERROR_CODES.filter((code) => !fromDashboard.has(code)).sort(),
      );
    },
  );
});

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

// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AdminApiError } from "@/api/client";

import { ApiErrorNotice } from "./api-error-notice";

afterEach(cleanup);

describe("ApiErrorNotice", () => {
  it("translates a known error code", () => {
    const error = new AdminApiError(
      "Redis is unavailable. Try again later.",
      503,
      "redis_unavailable",
    );

    render(<ApiErrorNotice error={error} locale="fr" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "L’API d’administration a renvoyé une erreur.",
    );
    expect(alert).toHaveTextContent(
      "Redis est indisponible. Réessayez plus tard.",
    );
    expect(alert).not.toHaveTextContent("Try again later");
    expect(alert).toHaveTextContent("HTTP 503 (redis_unavailable)");
  });

  it("shows a generic message and the English detail for an unknown code", () => {
    const error = new AdminApiError("Something new broke.", 500, null);

    render(<ApiErrorNotice error={error} locale="fr" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "L’API d’administration n’a pas pu traiter la demande.",
    );
    // toHaveTextContent turns the no-break space before ":" into a space.
    expect(alert).toHaveTextContent(
      "Détail (en anglais) : Something new broke.",
    );
  });
});

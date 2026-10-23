// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";

import { NavBar } from "./nav-bar";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn(),
}));

afterEach(cleanup);

describe("NavBar", () => {
  it("names the screens in the language of the page", () => {
    render(
      <LocaleProvider locale="fr">
        <NavBar locale="fr" />
      </LocaleProvider>,
    );

    const nav = screen.getByRole("navigation", {
      name: "Navigation principale",
    });
    expect(nav).toHaveTextContent("Administration de LLM Gateway");
    expect(
      screen.getByRole("link", { name: "Vue d’ensemble" }),
    ).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Clés" })).toHaveAttribute(
      "href",
      "/keys",
    );
    expect(
      screen.getByRole("button", { name: "Se déconnecter" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Langue")).toHaveValue("fr");
  });

  it("is in English by default", () => {
    render(<NavBar locale="en" />);

    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Operators" })).toHaveAttribute(
      "href",
      "/operators",
    );
    expect(screen.getByLabelText("Language")).toHaveValue("en");
  });
});

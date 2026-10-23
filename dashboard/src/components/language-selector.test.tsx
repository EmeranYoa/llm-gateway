// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";

import { LanguageSelector } from "./language-selector";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));

function clearLanguageCookie() {
  document.cookie = "lang=; Path=/; Max-Age=0";
}

beforeEach(() => {
  router.refresh.mockReset();
  clearLanguageCookie();
});

afterEach(() => {
  cleanup();
  clearLanguageCookie();
});

describe("LanguageSelector", () => {
  it("shows the language of the page, in that language", () => {
    render(
      <LocaleProvider locale="fr">
        <LanguageSelector />
      </LocaleProvider>,
    );

    const select = screen.getByLabelText("Langue");
    expect(select).toHaveValue("fr");
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Français" }),
    ).toBeInTheDocument();
  });

  it("is in English without a provider", () => {
    render(<LanguageSelector />);

    expect(screen.getByLabelText("Language")).toHaveValue("en");
  });

  it("only writes the lang cookie and reloads when nobody is signed in", () => {
    render(<LanguageSelector />);

    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr" },
    });

    expect(document.cookie).toContain("lang=fr");
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("saves the language in the account when signed in, then reloads", async () => {
    const save = vi.fn(async () => ({ saved: true }));
    render(<LanguageSelector save={save} />);

    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr" },
    });

    await waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith("fr");
    // The cookie keeps the language on the sign-in page after sign-out.
    expect(document.cookie).toContain("lang=fr");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says when the account could not be updated", async () => {
    const save = vi.fn(async () => ({ saved: false }));
    render(<LanguageSelector save={save} />);

    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The language could not be saved in your account.",
    );
  });

  it("ignores a value that is not a language", () => {
    render(<LanguageSelector />);
    const select = screen.getByLabelText("Language");
    const option = document.createElement("option");
    option.value = "xx";
    select.appendChild(option);

    fireEvent.change(select, { target: { value: "xx" } });

    expect(document.cookie).not.toContain("lang=");
    expect(router.refresh).not.toHaveBeenCalled();
  });
});

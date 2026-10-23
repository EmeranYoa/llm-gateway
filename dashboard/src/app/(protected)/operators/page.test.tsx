// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApiError } from "@/api/client";
import { listOperators } from "@/api/operators";
import { loadAccount } from "@/lib/account";

import OperatorsPage from "./page";

vi.mock("@/api/operators", () => ({ listOperators: vi.fn() }));

vi.mock("@/lib/account", () => ({ loadAccount: vi.fn() }));

vi.mock("@/lib/operator-actions", () => ({
  changeOwnPasswordAction: vi.fn(),
  createOperatorAction: vi.fn(),
  disableOperatorAction: vi.fn(),
  enableOperatorAction: vi.fn(),
  resetOperatorPasswordAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

afterEach(cleanup);

const OPERATORS = [
  {
    id: 1,
    username: "alice",
    enabled: true,
    must_change_password: false,
    created_at: "2026-10-01T08:00:00Z",
    last_sign_in_at: "2026-10-23T09:30:00Z",
  },
  {
    id: 2,
    username: "bob",
    enabled: true,
    must_change_password: true,
    created_at: "2026-10-20T08:00:00Z",
    last_sign_in_at: null,
  },
];

function signedInAs(username: string) {
  vi.mocked(loadAccount).mockResolvedValue({
    status: "signed-in",
    me: { username, must_change_password: false, language: null },
  });
}

describe("OperatorsPage", () => {
  it("lists the accounts, marks you, and shows the forms", async () => {
    vi.mocked(listOperators).mockResolvedValue(OPERATORS);
    signedInAs("alice");

    render(await OperatorsPage());

    expect(
      screen.getByRole("heading", { level: 1, name: "Operators" }),
    ).toBeInTheDocument();
    const alice = screen.getByRole("rowheader", { name: /alice/ });
    expect(within(alice).getByText("you")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Disable bob" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Create an account" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Change my password" }),
    ).toBeInTheDocument();
  });

  it("shows an error of the admin API instead of the list", async () => {
    vi.mocked(listOperators).mockRejectedValue(
      new AdminApiError("Database down.", 503, "database_unavailable"),
    );
    signedInAs("alice");

    render(await OperatorsPage());

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The database is unavailable. Try again later.",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // The password change still works.
    expect(
      screen.getByRole("button", { name: "Change my password" }),
    ).toBeInTheDocument();
  });
});

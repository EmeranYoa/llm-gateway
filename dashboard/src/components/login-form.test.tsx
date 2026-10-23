// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoginState } from "@/lib/auth-actions";

import { LoginForm } from "./login-form";

afterEach(cleanup);

describe("LoginForm", () => {
  it("renders a password field for the admin key and a sign-in button", () => {
    render(<LoginForm action={vi.fn()} />);

    const field = screen.getByLabelText("Admin key");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("name", "adminKey");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the error returned by the action", async () => {
    const action = vi.fn(async (): Promise<LoginState> => ({
      error: "This admin key is not valid, or it has been revoked.",
    }));
    render(<LoginForm action={action} />);

    fireEvent.change(screen.getByLabelText("Admin key"), {
      target: { value: "gwa_wrong_key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This admin key is not valid, or it has been revoked.",
    );
    const form = action.mock.calls[0] as unknown as [LoginState, FormData];
    expect(form[1].get("adminKey")).toBe("gwa_wrong_key");
  });

  it("shows a notice, for example after a session has ended", () => {
    render(<LoginForm action={vi.fn()} notice="Your session has ended." />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Your session has ended.",
    );
  });
});

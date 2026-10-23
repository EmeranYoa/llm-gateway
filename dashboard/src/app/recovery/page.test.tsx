// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getRecoveryStatus } from "@/api/operators";

import RecoveryPage from "./page";

vi.mock("@/api/operators", () => ({ getRecoveryStatus: vi.fn() }));

vi.mock("@/lib/auth-actions", () => ({ recoverAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

afterEach(cleanup);

describe("RecoveryPage", () => {
  it("asks for the recovery token, the username and the new password twice", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(true);

    render(await RecoveryPage());

    for (const label of [
      "Recovery token",
      "Username",
      "New password",
      "New password again",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Go to sign-in" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("opens the sign-in while recovery is off", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(false);

    await expect(RecoveryPage()).rejects.toThrow("redirect:/login");
  });
});

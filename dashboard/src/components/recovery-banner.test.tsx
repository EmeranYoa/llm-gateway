// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApiError } from "@/api/client";
import { getRecoveryStatus } from "@/api/operators";

import { RecoveryBanner } from "./recovery-banner";

vi.mock("@/api/operators", () => ({ getRecoveryStatus: vi.fn() }));

afterEach(cleanup);

async function renderBanner(locale: "en" | "fr" = "en") {
  const banner = await RecoveryBanner({ locale });
  render(<>{banner}</>);
}

describe("RecoveryBanner", () => {
  it("asks to turn recovery off while it is on", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(true);

    await renderBanner();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Account recovery is on. Once you are back in, remove OPERATOR_RECOVERY from the admin API settings and restart it.",
    );
  });

  it("speaks French", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(true);

    await renderBanner("fr");

    expect(screen.getByRole("status")).toHaveTextContent(
      "La récupération de compte est activée.",
    );
  });

  it("shows nothing while recovery is off", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(false);

    await renderBanner();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows nothing when the admin API cannot say", async () => {
    vi.mocked(getRecoveryStatus).mockRejectedValue(
      new AdminApiError("down", null, "admin_api_unreachable"),
    );

    await renderBanner();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

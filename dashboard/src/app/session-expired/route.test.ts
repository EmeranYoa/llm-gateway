import { describe, expect, it, vi } from "vitest";

import { GET } from "./route";

const session = vi.hoisted(() => ({
  token: "gws_ended_session" as string | undefined,
  destroy: vi.fn(),
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

describe("GET /session-expired", () => {
  it("destroys the session and opens the sign-in page with a notice", async () => {
    await expect(GET()).rejects.toThrow("redirect:/login?expired=1");

    expect(session.destroy).toHaveBeenCalledTimes(1);
  });
});

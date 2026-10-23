import { beforeEach, describe, expect, it, vi } from "vitest";

import { login, logout } from "./auth-actions";

const session = vi.hoisted(() => ({
  adminKey: undefined as string | undefined,
  save: vi.fn(async () => {}),
  destroy: vi.fn(),
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

const VALID_KEY = "gwa_valid_admin_key";

function formWithKey(key: string): FormData {
  const form = new FormData();
  form.set("adminKey", key);
  return form;
}

function stubAdminApi(status: number, body: unknown) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", "http://admin-api.test:8001");
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.adminKey = undefined;
  session.save.mockClear();
  session.destroy.mockClear();
});

describe("login", () => {
  it("stores a valid key in the session and opens the home page", async () => {
    const fetchMock = stubAdminApi(200, { name: "alice" });

    // A successful sign-in ends with a redirect: nothing is returned to the browser.
    await expect(
      login({ error: null }, formWithKey(`  ${VALID_KEY}  `)),
    ).rejects.toThrow("redirect:/");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(session.adminKey).toBe(VALID_KEY);
    expect(session.save).toHaveBeenCalledTimes(1);
  });

  it("does not store a key refused by the admin API and shows an error", async () => {
    stubAdminApi(401, {
      error: {
        message: "Missing or invalid API key.",
        code: "invalid_api_key",
      },
    });

    const state = await login({ error: null }, formWithKey("gwa_wrong_key"));

    expect(state.error).toMatch(/not valid/);
    expect(JSON.stringify(state)).not.toContain("gwa_wrong_key");
    expect(session.adminKey).toBeUndefined();
    expect(session.save).not.toHaveBeenCalled();
  });

  it("refuses a value that is not an admin key without calling the admin API", async () => {
    const fetchMock = stubAdminApi(200, { name: "alice" });

    const state = await login({ error: null }, formWithKey("gw_tenant_key"));

    expect(state.error).toMatch(/gwa_/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(session.save).not.toHaveBeenCalled();
  });

  it("shows an error when the admin API cannot check the key", async () => {
    stubAdminApi(503, {
      error: {
        message: "The database is unavailable. Try again later.",
        code: "database_unavailable",
      },
    });

    const state = await login({ error: null }, formWithKey(VALID_KEY));

    expect(state.error).toMatch(/database is unavailable/);
    expect(JSON.stringify(state)).not.toContain(VALID_KEY);
    expect(session.save).not.toHaveBeenCalled();
  });
});

describe("logout", () => {
  it("clears the session and opens the sign-in page", async () => {
    session.adminKey = VALID_KEY;

    await expect(logout()).rejects.toThrow("redirect:/login");

    expect(session.destroy).toHaveBeenCalledTimes(1);
  });
});

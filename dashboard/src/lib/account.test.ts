import { beforeEach, describe, expect, it, vi } from "vitest";

import { accountRedirect, loadAccount } from "./account";

const session = vi.hoisted(() => ({
  token: undefined as string | undefined,
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

function stubMe(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

const ME = { username: "alice", must_change_password: false, language: "fr" };

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", "http://admin-api.test:8001");
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.token = "gws_session";
});

describe("loadAccount", () => {
  it("is signed out without a session token, without calling the admin API", async () => {
    session.token = undefined;
    const fetchMock = stubMe(json(200, ME));

    await expect(loadAccount()).resolves.toEqual({ status: "signed-out" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads the account with the session token", async () => {
    const fetchMock = stubMe(json(200, ME));

    await expect(loadAccount()).resolves.toEqual({
      status: "signed-in",
      me: ME,
    });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/me");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer gws_session",
    );
  });

  it("is expired when the admin API refuses the session, without redirecting", async () => {
    stubMe(json(401, { error: { message: "no", code: "invalid_session" } }));

    await expect(loadAccount()).resolves.toEqual({ status: "expired" });
  });

  it("is unavailable when the admin API cannot answer", async () => {
    stubMe(new TypeError("fetch failed"));

    await expect(loadAccount()).resolves.toMatchObject({
      status: "unavailable",
      error: { code: "admin_api_unreachable" },
    });
  });
});

describe("accountRedirect", () => {
  it("sends an operator who must change their password to the change page", () => {
    expect(
      accountRedirect({
        status: "signed-in",
        me: { ...ME, must_change_password: true },
      }),
    ).toBe("/change-password");
  });

  it("lets a signed-in operator through", () => {
    expect(accountRedirect({ status: "signed-in", me: ME })).toBeNull();
  });

  it("ends a refused session and signs in a visitor without one", () => {
    expect(accountRedirect({ status: "expired" })).toBe("/session-expired");
    expect(accountRedirect({ status: "signed-out" })).toBe("/login");
  });
});

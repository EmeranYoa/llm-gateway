import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  changePasswordAction,
  recoverAction,
  setUpAction,
  signInAction,
  signOutAction,
} from "./auth-actions";

const session = vi.hoisted(() => ({
  token: undefined as string | undefined,
  save: vi.fn(async () => {}),
  destroy: vi.fn(),
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

const API = "http://admin-api.test:8001";
const SESSION_TOKEN = "gws_new_session_token";
const PASSWORD = "correct horse battery";
const IDLE = { error: null };
/** The redirect to the overview, and not to any other page. */
const OVERVIEW_REDIRECT = /^redirect:\/$/;

const OPENED = {
  token: SESSION_TOKEN,
  username: "alice",
  expires_at: "2026-10-23T18:00:00Z",
};

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function apiError(
  status: number,
  code: string,
  headers: Record<string, string> = {},
): Response {
  return jsonResponse(
    status,
    { error: { message: `English message (${code}).`, code } },
    headers,
  );
}

function stubAdminApi(...responses: (Response | Error)[]) {
  const fetchMock = vi.fn(async () => {
    const next = responses.shift();
    if (next === undefined) throw new Error("unexpected call");
    if (next instanceof Error) throw next;
    return next;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The URL, method, JSON body and Authorization header of a call to the admin API. */
function call(fetchMock: ReturnType<typeof stubAdminApi>, index = 0) {
  const [url, init] = fetchMock.mock.calls[index] as unknown as [
    string,
    RequestInit,
  ];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : JSON.parse(String(init.body)),
    authorization: new Headers(init.headers).get("Authorization"),
  };
}

function formOf(fields: Record<string, string>): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    form.set(name, value);
  }
  return form;
}

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", API);
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.token = undefined;
  session.save.mockClear();
  session.destroy.mockClear();
});

describe("signInAction", () => {
  const credentials = { username: "  alice ", password: PASSWORD };

  it("stores the session token in the cookie and opens the overview", async () => {
    const fetchMock = stubAdminApi(jsonResponse(201, OPENED));

    // A successful sign-in ends with a redirect: nothing is returned to the browser.
    await expect(signInAction(IDLE, formOf(credentials))).rejects.toThrow(
      OVERVIEW_REDIRECT,
    );

    expect(call(fetchMock)).toEqual({
      url: `${API}/admin/v1/sessions`,
      method: "POST",
      body: { username: "alice", password: PASSWORD },
      authorization: null,
    });
    expect(session.token).toBe(SESSION_TOKEN);
    expect(session.save).toHaveBeenCalledTimes(1);
  });

  it("returns the code of wrong credentials, and never the password", async () => {
    stubAdminApi(apiError(401, "invalid_credentials"));

    const state = await signInAction(IDLE, formOf(credentials));

    expect(state.error).toEqual({
      kind: "api",
      code: "invalid_credentials",
      message: "English message (invalid_credentials).",
      retryAfterSeconds: null,
    });
    expect(JSON.stringify(state)).not.toContain(PASSWORD);
    expect(session.save).not.toHaveBeenCalled();
  });

  it("returns the wait time of too many attempts", async () => {
    stubAdminApi(apiError(429, "too_many_attempts", { "retry-after": "600" }));

    const state = await signInAction(IDLE, formOf(credentials));

    expect(state.error).toMatchObject({
      code: "too_many_attempts",
      retryAfterSeconds: 600,
    });
  });

  it("returns the code of an unavailable check or an unreachable admin API", async () => {
    stubAdminApi(
      apiError(503, "authentication_unavailable"),
      new TypeError("fetch failed"),
    );

    expect((await signInAction(IDLE, formOf(credentials))).error).toMatchObject(
      {
        code: "authentication_unavailable",
      },
    );
    expect((await signInAction(IDLE, formOf(credentials))).error).toMatchObject(
      {
        code: "admin_api_unreachable",
      },
    );
  });

  it("refuses an empty field without calling the admin API", async () => {
    const fetchMock = stubAdminApi();

    const state = await signInAction(
      IDLE,
      formOf({ username: "alice", password: "" }),
    );

    expect(state.error).toEqual({ kind: "form", problem: "missingFields" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("setUpAction", () => {
  const setup = {
    token: " setup-token ",
    username: "alice",
    password: PASSWORD,
    passwordAgain: PASSWORD,
  };

  it("creates the first account, stores its session and opens the overview", async () => {
    const fetchMock = stubAdminApi(jsonResponse(201, OPENED));

    await expect(setUpAction(IDLE, formOf(setup))).rejects.toThrow(
      OVERVIEW_REDIRECT,
    );

    expect(call(fetchMock)).toMatchObject({
      url: `${API}/admin/v1/setup`,
      method: "POST",
      body: { token: "setup-token", username: "alice", password: PASSWORD },
    });
    expect(session.token).toBe(SESSION_TOKEN);
  });

  it("checks the passwords again on the server", async () => {
    const fetchMock = stubAdminApi();

    const differ = await setUpAction(
      IDLE,
      formOf({ ...setup, passwordAgain: "something else!" }),
    );
    const short = await setUpAction(
      IDLE,
      formOf({ ...setup, password: "short", passwordAgain: "short" }),
    );

    expect(differ.error).toEqual({ kind: "form", problem: "passwordsDiffer" });
    expect(short.error).toEqual({ kind: "form", problem: "passwordTooShort" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the code of a wrong token, and never the token", async () => {
    stubAdminApi(apiError(401, "invalid_setup_token"));

    const state = await setUpAction(IDLE, formOf(setup));

    expect(state.error).toMatchObject({ code: "invalid_setup_token" });
    expect(JSON.stringify(state)).not.toContain("setup-token");
    expect(session.save).not.toHaveBeenCalled();
  });
});

describe("changePasswordAction", () => {
  const change = {
    currentPassword: "old password 123",
    newPassword: PASSWORD,
    newPasswordAgain: PASSWORD,
  };

  beforeEach(() => {
    session.token = "gws_current";
  });

  it("changes the password with the session, then opens the overview", async () => {
    const fetchMock = stubAdminApi(new Response(null, { status: 204 }));

    await expect(changePasswordAction(IDLE, formOf(change))).rejects.toThrow(
      OVERVIEW_REDIRECT,
    );

    expect(call(fetchMock)).toEqual({
      url: `${API}/admin/v1/me/password`,
      method: "PUT",
      body: { current_password: "old password 123", new_password: PASSWORD },
      authorization: "Bearer gws_current",
    });
  });

  it("returns the code of a wrong current password", async () => {
    stubAdminApi(apiError(403, "reauthentication_failed"));

    const state = await changePasswordAction(IDLE, formOf(change));

    expect(state.error).toMatchObject({ code: "reauthentication_failed" });
    expect(JSON.stringify(state)).not.toContain(PASSWORD);
  });

  it("returns the code of a refused new password", async () => {
    stubAdminApi(apiError(400, "invalid_password"));

    expect(
      (await changePasswordAction(IDLE, formOf(change))).error,
    ).toMatchObject({ code: "invalid_password" });
  });

  it("refuses two different new passwords without calling the admin API", async () => {
    const fetchMock = stubAdminApi();

    const state = await changePasswordAction(
      IDLE,
      formOf({ ...change, newPasswordAgain: "another password" }),
    );

    expect(state.error).toEqual({ kind: "form", problem: "passwordsDiffer" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("recoverAction", () => {
  const recovery = {
    token: "recovery-token",
    username: "alice",
    newPassword: PASSWORD,
    newPasswordAgain: PASSWORD,
  };
  const START = { error: null, recoveredUsername: null };

  it("sets the new password and says for which account", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, { username: "Alice" }));

    const state = await recoverAction(START, formOf(recovery));

    expect(state).toEqual({ error: null, recoveredUsername: "Alice" });
    expect(call(fetchMock)).toEqual({
      url: `${API}/admin/v1/recovery`,
      method: "POST",
      body: {
        token: "recovery-token",
        username: "alice",
        new_password: PASSWORD,
      },
      authorization: null,
    });
    // Recovery never signs in: the operator signs in with the new password.
    expect(session.save).not.toHaveBeenCalled();
  });

  it.each([
    [404, "recovery_disabled"],
    [404, "recovery_used"],
    [401, "invalid_recovery_token"],
    [404, "operator_not_found"],
    [400, "invalid_password"],
  ])("returns the code of an HTTP %i %s", async (status, code) => {
    stubAdminApi(apiError(status, code));

    const state = await recoverAction(START, formOf(recovery));

    expect(state.recoveredUsername).toBeNull();
    expect(state.error).toMatchObject({ kind: "api", code });
    expect(JSON.stringify(state)).not.toContain("recovery-token");
  });
});

describe("signOutAction", () => {
  it("ends the session on the admin API, then clears the cookie", async () => {
    session.token = "gws_current";
    const fetchMock = stubAdminApi(new Response(null, { status: 204 }));

    await expect(signOutAction()).rejects.toThrow("redirect:/login");

    expect(call(fetchMock)).toMatchObject({
      url: `${API}/admin/v1/sessions/current`,
      method: "DELETE",
      authorization: "Bearer gws_current",
    });
    expect(session.destroy).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.invocationCallOrder[0]).toBeLessThan(
      session.destroy.mock.invocationCallOrder[0],
    );
  });

  it("clears the cookie even when the admin API fails", async () => {
    session.token = "gws_current";
    stubAdminApi(new TypeError("fetch failed"));

    await expect(signOutAction()).rejects.toThrow("redirect:/login");

    expect(session.destroy).toHaveBeenCalledTimes(1);
  });

  it("clears the cookie even when the admin API refuses the session", async () => {
    session.token = "gws_ended";
    stubAdminApi(apiError(401, "invalid_session"));

    await expect(signOutAction()).rejects.toThrow("redirect:/login");

    expect(session.destroy).toHaveBeenCalledTimes(1);
  });

  it("does not call the admin API without a session", async () => {
    const fetchMock = stubAdminApi();

    await expect(signOutAction()).rejects.toThrow("redirect:/login");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(session.destroy).toHaveBeenCalledTimes(1);
  });
});

import { revalidatePath } from "next/cache";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  changeOwnPasswordAction,
  createOperatorAction,
  disableOperatorAction,
  enableOperatorAction,
  resetOperatorPasswordAction,
} from "./operator-actions";

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

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const API = "http://admin-api.test:8001";
const SESSION_TOKEN = "gws_session_token";
const MY_PASSWORD = "my current password";
const NEW_PASSWORD = "a brand new password";
const IDLE = { error: null, done: null };

const BOB = {
  id: 7,
  username: "bob",
  enabled: true,
  must_change_password: true,
  created_at: "2026-10-20T08:00:00Z",
  last_sign_in_at: null,
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiError(status: number, code: string): Response {
  return jsonResponse(status, {
    error: { message: `English message (${code}).`, code },
  });
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

/** The URL, method, JSON body and Authorization header of the only call. */
function onlyCall(fetchMock: ReturnType<typeof stubAdminApi>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
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

/** No password in what goes back to the browser. */
function expectNoPassword(result: unknown) {
  const text = JSON.stringify(result);
  expect(text).not.toContain(MY_PASSWORD);
  expect(text).not.toContain(NEW_PASSWORD);
}

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", API);
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.token = SESSION_TOKEN;
  vi.mocked(revalidatePath).mockClear();
});

describe("createOperatorAction", () => {
  const fields = {
    username: "  bob ",
    password: NEW_PASSWORD,
    passwordAgain: NEW_PASSWORD,
    currentPassword: MY_PASSWORD,
  };

  it("creates the account with the current password and revalidates the page", async () => {
    const fetchMock = stubAdminApi(jsonResponse(201, BOB));

    const result = await createOperatorAction(IDLE, formOf(fields));

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/operators`,
      method: "POST",
      body: {
        username: "bob",
        password: NEW_PASSWORD,
        current_password: MY_PASSWORD,
      },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(result).toEqual({ error: null, done: { username: "bob" } });
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it.each([
    [409, "operator_exists"],
    [403, "reauthentication_failed"],
    [400, "invalid_password"],
  ])("returns the code of a %i %s", async (status, code) => {
    stubAdminApi(apiError(status, code));

    const result = await createOperatorAction(IDLE, formOf(fields));

    expect(result).toEqual({
      error: {
        kind: "api",
        code,
        message: `English message (${code}).`,
        retryAfterSeconds: null,
      },
      done: null,
    });
    expectNoPassword(result);
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it("checks the form again on the server, without calling the admin API", async () => {
    const fetchMock = stubAdminApi();

    const result = await createOperatorAction(
      IDLE,
      formOf({ ...fields, passwordAgain: "something else entirely" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toEqual({
      error: { kind: "form", problem: "passwordsDiffer" },
      done: null,
    });
  });

  it("refuses a form without the current password", async () => {
    const fetchMock = stubAdminApi();

    const result = await createOperatorAction(
      IDLE,
      formOf({ ...fields, currentPassword: "" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toEqual({ kind: "form", problem: "missingFields" });
  });

  it("says when the admin API cannot be reached", async () => {
    stubAdminApi(new TypeError("fetch failed"));

    const result = await createOperatorAction(IDLE, formOf(fields));

    expect(result.error).toMatchObject({
      kind: "api",
      code: "admin_api_unreachable",
    });
    expectNoPassword(result);
  });

  it("ends a session refused by the admin API", async () => {
    stubAdminApi(apiError(401, "invalid_session"));

    await expect(createOperatorAction(IDLE, formOf(fields))).rejects.toThrow(
      "redirect:/session-expired",
    );
  });
});

describe("resetOperatorPasswordAction", () => {
  const fields = {
    operatorId: "7",
    password: NEW_PASSWORD,
    passwordAgain: NEW_PASSWORD,
    currentPassword: MY_PASSWORD,
  };

  it("sends the new password and the current one to the account", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, BOB));

    const result = await resetOperatorPasswordAction(IDLE, formOf(fields));

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/operators/7/reset-password`,
      method: "POST",
      body: { password: NEW_PASSWORD, current_password: MY_PASSWORD },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(result).toEqual({ error: null, done: { username: "bob" } });
    expectNoPassword(result);
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it.each([
    [400, "use_own_password_change"],
    [404, "operator_not_found"],
    [403, "reauthentication_failed"],
  ])("returns the code of a %i %s", async (status, code) => {
    stubAdminApi(apiError(status, code));

    const result = await resetOperatorPasswordAction(IDLE, formOf(fields));

    expect(result.error).toMatchObject({ kind: "api", code });
    expect(result.done).toBeNull();
    expectNoPassword(result);
  });

  it("refuses a password that is too short", async () => {
    const fetchMock = stubAdminApi();

    const result = await resetOperatorPasswordAction(
      IDLE,
      formOf({ ...fields, password: "short", passwordAgain: "short" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toEqual({ kind: "form", problem: "passwordTooShort" });
  });

  it("refuses a form without a valid account id", async () => {
    const fetchMock = stubAdminApi();

    const result = await resetOperatorPasswordAction(
      IDLE,
      formOf({ ...fields, operatorId: "../sessions" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toEqual({ kind: "form", problem: "missingFields" });
  });
});

describe("disableOperatorAction", () => {
  const fields = { operatorId: "7", currentPassword: MY_PASSWORD };

  it("disables the account with the current password", async () => {
    const fetchMock = stubAdminApi(
      jsonResponse(200, { ...BOB, enabled: false }),
    );

    const result = await disableOperatorAction(IDLE, formOf(fields));

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/operators/7/disable`,
      method: "POST",
      body: { current_password: MY_PASSWORD },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(result).toEqual({ error: null, done: { username: "bob" } });
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it.each([
    [400, "cannot_disable_self"],
    [400, "last_enabled_operator"],
    [404, "operator_not_found"],
    [403, "reauthentication_failed"],
  ])("returns the code of a %i %s", async (status, code) => {
    stubAdminApi(apiError(status, code));

    const result = await disableOperatorAction(IDLE, formOf(fields));

    expect(result.error).toMatchObject({ kind: "api", code });
    expectNoPassword(result);
    // The list may be stale: it is read again.
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it("asks for the current password before calling the admin API", async () => {
    const fetchMock = stubAdminApi();

    const result = await disableOperatorAction(
      IDLE,
      formOf({ operatorId: "7", currentPassword: "" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toEqual({ kind: "form", problem: "missingFields" });
  });
});

describe("enableOperatorAction", () => {
  it("enables the account with the current password", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, BOB));

    const result = await enableOperatorAction(
      IDLE,
      formOf({ operatorId: "7", currentPassword: MY_PASSWORD }),
    );

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/operators/7/enable`,
      method: "POST",
      body: { current_password: MY_PASSWORD },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(result).toEqual({ error: null, done: { username: "bob" } });
  });

  it("returns the code of an unknown account", async () => {
    stubAdminApi(apiError(404, "operator_not_found"));

    const result = await enableOperatorAction(
      IDLE,
      formOf({ operatorId: "7", currentPassword: MY_PASSWORD }),
    );

    expect(result.error).toMatchObject({ code: "operator_not_found" });
    expectNoPassword(result);
  });
});

describe("changeOwnPasswordAction", () => {
  const fields = {
    currentPassword: MY_PASSWORD,
    newPassword: NEW_PASSWORD,
    newPasswordAgain: NEW_PASSWORD,
  };
  const UNCHANGED = { error: null, changed: false };

  it("changes the password and stays on the page", async () => {
    const fetchMock = stubAdminApi(
      jsonResponse(200, {
        username: "alice",
        must_change_password: false,
        language: null,
      }),
    );

    const result = await changeOwnPasswordAction(UNCHANGED, formOf(fields));

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/me/password`,
      method: "PUT",
      body: { current_password: MY_PASSWORD, new_password: NEW_PASSWORD },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(result).toEqual({ error: null, changed: true });
    expect(revalidatePath).toHaveBeenCalledWith("/operators");
  });

  it("returns the code of a wrong current password", async () => {
    stubAdminApi(apiError(403, "reauthentication_failed"));

    const result = await changeOwnPasswordAction(UNCHANGED, formOf(fields));

    expect(result).toEqual({
      error: {
        kind: "api",
        code: "reauthentication_failed",
        message: "English message (reauthentication_failed).",
        retryAfterSeconds: null,
      },
      changed: false,
    });
    expectNoPassword(result);
  });

  it("refuses two different new passwords without calling the admin API", async () => {
    const fetchMock = stubAdminApi();

    const result = await changeOwnPasswordAction(
      UNCHANGED,
      formOf({ ...fields, newPasswordAgain: "not the same password" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toEqual({
      error: { kind: "form", problem: "passwordsDiffer" },
      changed: false,
    });
  });
});

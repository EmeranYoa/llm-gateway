import { revalidatePath } from "next/cache";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearCacheAction,
  createKeyAction,
  loadActionsAction,
  revokeKeyAction,
  setLimitsAction,
} from "./key-actions";

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

const SESSION_TOKEN = "gws_session_token";
const API = "http://admin-api.test:8001";
const FULL_KEY = "gw_" + "k".repeat(43);
const IDLE = { status: "idle" } as const;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiError(status: number, message: string, code: string | null = null) {
  return jsonResponse(status, {
    error: { message, type: "invalid_request_error", param: null, code },
  });
}

function stubAdminApi(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The URL, method and JSON body of the only call to the admin API. */
function onlyCall(fetchMock: ReturnType<typeof stubAdminApi>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  const headers = new Headers(init.headers);
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : JSON.parse(String(init.body)),
    authorization: headers.get("Authorization"),
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
  session.token = SESSION_TOKEN;
  session.save.mockClear();
  session.destroy.mockClear();
  vi.mocked(revalidatePath).mockClear();
});

describe("createKeyAction", () => {
  const created = { id: 7, tenant: "acme", prefix: "gw_kkkkkk", key: FULL_KEY };

  it("posts the tenant and the limits given, and returns the key once", async () => {
    const fetchMock = stubAdminApi(jsonResponse(201, created));

    const state = await createKeyAction(
      IDLE,
      formOf({ tenant: " acme ", rpm: "30", tokens_per_day: "" }),
    );

    expect(onlyCall(fetchMock)).toEqual({
      url: `${API}/admin/v1/keys`,
      method: "POST",
      body: { tenant: "acme", rpm: 30 },
      authorization: `Bearer ${SESSION_TOKEN}`,
    });
    expect(state).toEqual({ status: "created", key: created });
    expect(revalidatePath).toHaveBeenCalledWith("/keys");
  });

  it("never writes the created key to the session", async () => {
    stubAdminApi(jsonResponse(201, created));

    await createKeyAction(IDLE, formOf({ tenant: "acme" }));

    expect(session.save).not.toHaveBeenCalled();
    expect(JSON.stringify(session)).not.toContain(FULL_KEY);
  });

  it("refuses a missing tenant or a bad limit without calling the admin API", async () => {
    const fetchMock = stubAdminApi(jsonResponse(201, created));

    await expect(
      createKeyAction(IDLE, formOf({ tenant: "  " })),
    ).resolves.toEqual({
      status: "error",
      error: { kind: "form", problem: "missingTenantName" },
    });
    await expect(
      createKeyAction(IDLE, formOf({ tenant: "acme", rpm: "-3" })),
    ).resolves.toEqual({
      status: "error",
      error: { kind: "form", problem: "notWholeNumber", field: "rpm" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the validation error of the admin API", async () => {
    stubAdminApi(
      apiError(
        400,
        "Invalid value for 'rpm': Input should be less than or equal to 2147483647",
      ),
    );

    const state = await createKeyAction(
      IDLE,
      formOf({ tenant: "acme", rpm: "99999999999" }),
    );

    expect(state).toEqual({
      status: "error",
      error: {
        kind: "api",
        status: 400,
        code: null,
        message:
          "Invalid value for 'rpm': Input should be less than or equal to 2147483647",
      },
    });
  });

  it("ends the session when the admin API refuses the session", async () => {
    stubAdminApi(
      apiError(401, "Missing, invalid or expired session.", "invalid_session"),
    );

    await expect(
      createKeyAction(IDLE, formOf({ tenant: "acme" })),
    ).rejects.toThrow("redirect:/session-expired");
  });

  it("opens the password change page when the password must be changed", async () => {
    stubAdminApi(
      apiError(403, "Change your password first.", "password_change_required"),
    );

    await expect(
      createKeyAction(IDLE, formOf({ tenant: "acme" })),
    ).rejects.toThrow("redirect:/change-password");
  });
});

describe("revokeKeyAction", () => {
  const revoked = {
    id: 7,
    tenant: "acme",
    prefix: "gw_kkkkkk",
    created_at: "2026-10-20T10:00:00Z",
    last_used_at: null,
    revoked_at: "2026-10-23T10:00:00Z",
  };

  it("posts to the revoke endpoint of the key", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, revoked));

    const state = await revokeKeyAction(IDLE, formOf({ keyId: "7" }));

    const call = onlyCall(fetchMock);
    expect(call.url).toBe(`${API}/admin/v1/keys/7/revoke`);
    expect(call.method).toBe("POST");
    expect(call.body).toBeUndefined();
    expect(state).toEqual({ status: "revoked", prefix: "gw_kkkkkk" });
    expect(revalidatePath).toHaveBeenCalledWith("/keys");
  });

  it.each([
    [404, "No API key with id 7.", "key_not_found"],
    [409, "API key 7 is already revoked.", "key_already_revoked"],
  ])(
    "returns the error of a %i and refreshes the page",
    async (status, message, code) => {
      stubAdminApi(apiError(status, message, code));

      const state = await revokeKeyAction(IDLE, formOf({ keyId: "7" }));

      expect(state).toEqual({
        status: "error",
        error: { kind: "api", status, code, message },
      });
      expect(revalidatePath).toHaveBeenCalledWith("/keys");
    },
  );

  it("refuses a form without a key id", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, revoked));

    const state = await revokeKeyAction(IDLE, formOf({ keyId: "abc" }));

    expect(state).toEqual({
      status: "error",
      error: { kind: "form", problem: "missingKeyId" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("setLimitsAction", () => {
  const view = {
    tenant: "acme corp",
    limits: { rpm: 10, tokens_per_day: null },
    effective_limits: { rpm: 10, tokens_per_day: 100000 },
  };

  it("puts the limits given to the limits of the tenant", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, view));

    const state = await setLimitsAction(
      IDLE,
      formOf({ tenant: "acme corp", rpm: "10", tokens_per_day: "" }),
    );

    expect(onlyCall(fetchMock)).toMatchObject({
      url: `${API}/admin/v1/tenants/acme%20corp/limits`,
      method: "PUT",
      body: { rpm: 10 },
    });
    expect(state).toEqual({ status: "saved" });
  });

  it("asks for at least one limit", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, view));

    const state = await setLimitsAction(
      IDLE,
      formOf({ tenant: "acme", rpm: "", tokens_per_day: "" }),
    );

    expect(state).toEqual({
      status: "error",
      error: { kind: "form", problem: "noLimitGiven" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an unknown tenant", async () => {
    stubAdminApi(apiError(404, "Unknown tenant 'ghost'.", "tenant_not_found"));

    const state = await setLimitsAction(
      IDLE,
      formOf({ tenant: "ghost", rpm: "5" }),
    );

    expect(state).toEqual({
      status: "error",
      error: {
        kind: "api",
        status: 404,
        code: "tenant_not_found",
        message: "Unknown tenant 'ghost'.",
      },
    });
  });
});

describe("clearCacheAction", () => {
  it("clears the cache of a tenant and returns how many answers were removed", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, { removed: 4 }));

    const state = await clearCacheAction(
      IDLE,
      formOf({ tenant: "acme", alias: "" }),
    );

    expect(onlyCall(fetchMock)).toMatchObject({
      url: `${API}/admin/v1/cache/clear`,
      method: "POST",
      body: { tenant: "acme" },
    });
    expect(state).toEqual({
      status: "cleared",
      removed: 4,
      tenant: "acme",
      alias: null,
    });
  });

  it("clears one alias only when one is given", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, { removed: 1 }));

    await clearCacheAction(
      IDLE,
      formOf({ tenant: "acme", alias: " chat-fast " }),
    );

    expect(onlyCall(fetchMock).body).toEqual({
      tenant: "acme",
      alias: "chat-fast",
    });
  });

  it("shows when Redis is unavailable", async () => {
    stubAdminApi(
      apiError(
        503,
        "Redis is unavailable. Try again later.",
        "redis_unavailable",
      ),
    );

    const state = await clearCacheAction(IDLE, formOf({ tenant: "acme" }));

    expect(state).toEqual({
      status: "error",
      error: {
        kind: "api",
        status: 503,
        code: "redis_unavailable",
        message: "Redis is unavailable. Try again later.",
      },
    });
  });

  it("shows when the admin API cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );

    const state = await clearCacheAction(IDLE, formOf({ tenant: "acme" }));

    expect(state).toMatchObject({
      status: "error",
      error: { kind: "api", status: null, code: "admin_api_unreachable" },
    });
  });
});

describe("loadActionsAction", () => {
  it("gets the page of actions older than the cursor", async () => {
    const page = { actions: [], next_before: null };
    const fetchMock = stubAdminApi(jsonResponse(200, page));

    const result = await loadActionsAction(42);

    const call = onlyCall(fetchMock);
    expect(call.method).toBe("GET");
    const url = new URL(call.url);
    expect(url.pathname).toBe("/admin/v1/actions");
    expect(url.searchParams.get("before")).toBe("42");
    expect(url.searchParams.get("limit")).toBe("20");
    expect(result).toEqual({ status: "loaded", page });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("shows an error of the admin API", async () => {
    stubAdminApi(
      apiError(503, "The database is unavailable. Try again later.", null),
    );

    await expect(loadActionsAction(42)).resolves.toEqual({
      status: "error",
      error: {
        kind: "api",
        status: 503,
        code: null,
        message: "The database is unavailable. Try again later.",
      },
    });
  });

  it("refuses a cursor that is not a whole number", async () => {
    const fetchMock = stubAdminApi(jsonResponse(200, {}));

    await expect(loadActionsAction(1.5)).resolves.toEqual({
      status: "error",
      error: { kind: "form", problem: "noMoreActions" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

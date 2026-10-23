import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminApiError,
  callWithoutSession,
  callWithSession,
  getMe,
  getOverview,
  getRequest,
  getTargets,
  getTenantStatistics,
  listTenantNames,
  keepApiError,
  listRequests,
  parseRetryAfter,
} from "./client";

const session = vi.hoisted(() => ({
  token: undefined as string | undefined,
  save: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

const request = vi.hoisted(() => ({ headers: new Headers() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
  headers: async () => request.headers,
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

const SESSION_TOKEN = "gws_test_session";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", "http://admin-api.test:8001");
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.token = SESSION_TOKEN;
});

describe("getMe", () => {
  it("sends the session token to the admin API", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { name: "alice" }));

    await expect(getMe()).resolves.toEqual({ name: "alice" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/me");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${SESSION_TOKEN}`,
    );
  });

  it("sends to the sign-in page without a session", async () => {
    session.token = undefined;
    const fetchMock = stubFetch(jsonResponse(200, { name: "alice" }));

    await expect(getMe()).rejects.toThrow("redirect:/login");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ends the session when the admin API refuses it", async () => {
    stubFetch(
      jsonResponse(401, {
        error: {
          message: "Missing, invalid or expired session. Sign in again.",
          type: "invalid_request_error",
          param: null,
          code: "invalid_session",
        },
      }),
    );

    // The route at /session-expired destroys the session, then sends to /login:
    // a page being rendered is not allowed to change cookies itself.
    await expect(getMe()).rejects.toThrow("redirect:/session-expired");
  });

  it("raises a typed error with the message of the admin API", async () => {
    stubFetch(
      jsonResponse(503, {
        error: {
          message: "The database is unavailable. Try again later.",
          type: "api_error",
          param: null,
          code: "database_unavailable",
        },
      }),
    );

    const error = await getMe().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AdminApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "database_unavailable",
      message: "The database is unavailable. Try again later.",
    });
    expect(session.destroy).not.toHaveBeenCalled();
  });

  it("raises a typed error when the answer is not in the error format", async () => {
    stubFetch(new Response("Bad gateway", { status: 502 }));

    await expect(getMe()).rejects.toMatchObject({
      name: "AdminApiError",
      status: 502,
      code: null,
    });
  });

  it("raises a typed error when the admin API cannot be reached", async () => {
    stubFetch(new TypeError("fetch failed"));

    await expect(getMe()).rejects.toMatchObject({
      name: "AdminApiError",
      status: null,
      code: "admin_api_unreachable",
    });
  });
});

describe("callWithSession", () => {
  it("opens the password change page while the password must be changed", async () => {
    stubFetch(
      jsonResponse(403, {
        error: {
          message: "Change your password first.",
          code: "password_change_required",
        },
      }),
    );

    await expect(callWithSession("/admin/v1/overview")).rejects.toThrow(
      "redirect:/change-password",
    );
    expect(session.destroy).not.toHaveBeenCalled();
  });

  it("raises any other 403 as a typed error", async () => {
    stubFetch(
      jsonResponse(403, {
        error: { message: "Wrong password.", code: "reauthentication_failed" },
      }),
    );

    await expect(
      callWithSession("/admin/v1/me/password", { method: "PUT", body: {} }),
    ).rejects.toMatchObject({ status: 403, code: "reauthentication_failed" });
  });

  it("returns undefined for an answer without a body (204)", async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(
      callWithSession("/admin/v1/sessions/current", { method: "DELETE" }),
    ).resolves.toBeUndefined();
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.method).toBe("DELETE");
  });
});

describe("the browser's address", () => {
  it("is forwarded to the admin API, which limits sign-ins per address", async () => {
    request.headers = new Headers({
      "x-forwarded-for": "203.0.113.7, 10.0.0.2",
    });
    const fetchMock = stubFetch(jsonResponse(200, { open: false }));

    await callWithoutSession("/admin/v1/setup");

    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect((init.headers as Record<string, string>)["X-Forwarded-For"]).toBe(
      "203.0.113.7",
    );
    request.headers = new Headers();
  });

  it("is left out when the request has none", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { open: false }));

    await callWithoutSession("/admin/v1/setup");

    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.headers).not.toHaveProperty("X-Forwarded-For");
  });
});

describe("callWithoutSession", () => {
  it("sends no Authorization header and keeps the wait time of a 429", async () => {
    const fetchMock = stubFetch(
      new Response(
        JSON.stringify({
          error: { message: "Too many attempts.", code: "too_many_attempts" },
        }),
        { status: 429, headers: { "retry-after": "42" } },
      ),
    );

    const error = await callWithoutSession("/admin/v1/sessions", {
      method: "POST",
      body: { username: "alice", password: "x" },
    }).catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      status: 429,
      code: "too_many_attempts",
      retryAfterSeconds: 42,
    });
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
    expect(session.destroy).not.toHaveBeenCalled();
  });

  it("never redirects on a 401", async () => {
    stubFetch(
      jsonResponse(401, {
        error: { message: "Wrong.", code: "invalid_credentials" },
      }),
    );

    await expect(
      callWithoutSession("/admin/v1/sessions", { method: "POST", body: {} }),
    ).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
  });
});

describe("parseRetryAfter", () => {
  it("reads seconds", () => {
    expect(parseRetryAfter("120")).toBe(120);
    expect(parseRetryAfter(" 0 ")).toBe(0);
  });

  it("reads an HTTP date", () => {
    const now = Date.parse("2026-10-23T10:00:00Z");

    expect(parseRetryAfter("Fri, 23 Oct 2026 10:01:30 GMT", now)).toBe(90);
    expect(parseRetryAfter("Fri, 23 Oct 2026 09:00:00 GMT", now)).toBe(0);
  });

  it("gives null for a missing or invalid header", () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("")).toBeNull();
    expect(parseRetryAfter("soon")).toBeNull();
    expect(parseRetryAfter("-5")).toBeNull();
  });
});

describe("getOverview", () => {
  it("asks for the period, for every tenant", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { period: "7d" }));

    await expect(getOverview("7d", null)).resolves.toEqual({ period: "7d" });

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/overview?period=7d");
  });

  it("asks for one tenant, with its name encoded", async () => {
    const fetchMock = stubFetch(jsonResponse(200, {}));

    await getOverview("24h", "acme & co");

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(
      "http://admin-api.test:8001/admin/v1/overview?period=24h&tenant=acme+%26+co",
    );
  });
});

describe("listTenantNames", () => {
  it("asks for the names only", async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, { tenants: ["acme", "beta"] }),
    );

    await expect(listTenantNames()).resolves.toEqual(["acme", "beta"]);

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/tenant-names");
  });
});

describe("getTenantStatistics", () => {
  it("asks for the period", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { tenants: [] }));

    await expect(getTenantStatistics("30d")).resolves.toEqual({ tenants: [] });

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/tenants?period=30d");
  });
});

describe("getTargets", () => {
  it("asks for the period", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { targets: [] }));

    await expect(getTargets("7d")).resolves.toEqual({ targets: [] });

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/targets?period=7d");
  });
});

describe("listRequests", () => {
  const noFilter = {
    period: "24h",
    tenant: null,
    alias: null,
    status: null,
  } as const;

  it("asks for the period only when there is no other filter", async () => {
    const page = { items: [], next_cursor: null };
    const fetchMock = stubFetch(jsonResponse(200, page));

    await expect(listRequests(noFilter, null)).resolves.toEqual(page);

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/requests?period=24h");
  });

  it("sends every filter and the cursor, encoded", async () => {
    const fetchMock = stubFetch(jsonResponse(200, {}));

    await listRequests(
      {
        period: "30d",
        tenant: "acme & co",
        alias: "chat/fast",
        status: "client_error",
      },
      "MjAyNi0xMC0yMyByZXEtMQ==",
    );

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(
      "http://admin-api.test:8001/admin/v1/requests?period=30d&tenant=acme+%26+co&alias=chat%2Ffast&status=client_error&cursor=MjAyNi0xMC0yMyByZXEtMQ%3D%3D",
    );
  });

  it("raises the error of an invalid cursor", async () => {
    stubFetch(
      jsonResponse(400, {
        error: { message: "Invalid cursor.", code: "invalid_cursor" },
      }),
    );

    await expect(listRequests(noFilter, "nope")).rejects.toMatchObject({
      status: 400,
      code: "invalid_cursor",
    });
  });
});

describe("getRequest", () => {
  it("asks for one request, with its id encoded", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { request_id: "a/b?c" }));

    await expect(getRequest("a/b?c")).resolves.toEqual({
      request_id: "a/b?c",
    });

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/requests/a%2Fb%3Fc");
  });

  it("raises a 404 for an unknown request", async () => {
    stubFetch(
      jsonResponse(404, {
        error: {
          message: "No request with this id.",
          code: "request_not_found",
        },
      }),
    );

    await expect(getRequest("nope")).rejects.toMatchObject({
      status: 404,
      code: "request_not_found",
    });
  });
});

describe("keepApiError", () => {
  it("returns an error of the admin API, to show on the page", () => {
    const error = new AdminApiError("boom", 500, null);

    expect(keepApiError(error)).toBe(error);
  });

  it("throws anything else again, such as a redirect", () => {
    const redirect = new Error("redirect:/login");

    expect(() => keepApiError(redirect)).toThrow(redirect);
  });
});

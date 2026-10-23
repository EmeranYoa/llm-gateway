import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminApiError,
  checkAdminKey,
  getMe,
  getOverview,
  getRequest,
  getTargets,
  getTenantStatistics,
  keepApiError,
  listRequests,
} from "./client";

const session = vi.hoisted(() => ({
  adminKey: undefined as string | undefined,
  save: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

const ADMIN_KEY = "gwa_test_key";

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
  session.adminKey = ADMIN_KEY;
});

describe("getMe", () => {
  it("sends the admin key of the session to the admin API", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { name: "alice" }));

    await expect(getMe()).resolves.toEqual({ name: "alice" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/me");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${ADMIN_KEY}`,
    );
  });

  it("sends to the sign-in page when the session has no key", async () => {
    session.adminKey = undefined;
    const fetchMock = stubFetch(jsonResponse(200, { name: "alice" }));

    await expect(getMe()).rejects.toThrow("redirect:/login");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ends the session when the admin API refuses the key", async () => {
    stubFetch(
      jsonResponse(401, {
        error: {
          message: "Missing or invalid API key.",
          type: "invalid_request_error",
          param: null,
          code: "invalid_api_key",
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

describe("checkAdminKey", () => {
  it("returns the operator when the key is valid", async () => {
    const fetchMock = stubFetch(jsonResponse(200, { name: "alice" }));

    await expect(checkAdminKey("gwa_other")).resolves.toEqual({
      name: "alice",
    });
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer gwa_other",
    );
  });

  it("returns null when the key is refused, without touching the session", async () => {
    stubFetch(jsonResponse(401, { error: { message: "no" } }));

    await expect(checkAdminKey("gwa_wrong")).resolves.toBeNull();
    expect(session.destroy).not.toHaveBeenCalled();
  });

  it("raises a typed error for other failures", async () => {
    stubFetch(jsonResponse(500, { error: { message: "boom" } }));

    await expect(checkAdminKey("gwa_other")).rejects.toBeInstanceOf(
      AdminApiError,
    );
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

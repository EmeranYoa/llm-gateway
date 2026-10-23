import { beforeEach, describe, expect, it, vi } from "vitest";

import { saveLanguageAction } from "./language-actions";

const session = vi.hoisted(() => ({
  token: "gws_current" as string | undefined,
}));

vi.mock("@/lib/session", () => ({ getSession: async () => session }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

function stubAdminApi(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubEnv("ADMIN_API_URL", "http://admin-api.test:8001");
  vi.stubEnv("DASHBOARD_SESSION_SECRET", "x".repeat(32));
  session.token = "gws_current";
});

describe("saveLanguageAction", () => {
  it("saves the language in the account of the session", async () => {
    const fetchMock = stubAdminApi(
      new Response(
        JSON.stringify({
          username: "alice",
          must_change_password: false,
          language: "fr",
        }),
        { status: 200 },
      ),
    );

    await expect(saveLanguageAction("fr")).resolves.toEqual({ saved: true });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://admin-api.test:8001/admin/v1/me/language");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ language: "fr" });
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer gws_current",
    );
  });

  it("refuses a value that is not a language without calling the admin API", async () => {
    const fetchMock = stubAdminApi(new Response(null, { status: 204 }));

    await expect(saveLanguageAction("de")).resolves.toEqual({ saved: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says when the admin API could not save it", async () => {
    stubAdminApi(
      new Response(
        JSON.stringify({
          error: { message: "down", code: "database_unavailable" },
        }),
        { status: 503 },
      ),
    );

    await expect(saveLanguageAction("en")).resolves.toEqual({ saved: false });
  });
});

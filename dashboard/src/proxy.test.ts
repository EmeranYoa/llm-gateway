import { sealData } from "iron-session";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_COOKIE_NAME } from "@/lib/session-options";

import { proxy } from "./proxy";

const SECRET = "x".repeat(32);

function requestWithCookie(cookie?: string): NextRequest {
  const headers = new Headers();
  if (cookie) headers.set("cookie", `${SESSION_COOKIE_NAME}=${cookie}`);
  return new NextRequest("http://localhost:3000/tenants", { headers });
}

beforeEach(() => {
  vi.stubEnv("DASHBOARD_SESSION_SECRET", SECRET);
});

describe("proxy", () => {
  it("sends a visitor without a session to the sign-in page", async () => {
    const response = await proxy(requestWithCookie());

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
  });

  it("sends a visitor with a forged cookie to the sign-in page", async () => {
    const response = await proxy(requestWithCookie("not-a-sealed-session"));

    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
  });

  it("lets a signed-in operator through", async () => {
    const sealed = await sealData(
      { adminKey: "gwa_key" },
      { password: SECRET },
    );

    const response = await proxy(requestWithCookie(sealed));

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});

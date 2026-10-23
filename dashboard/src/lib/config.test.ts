import { describe, expect, it } from "vitest";

import { DashboardConfigError, readDashboardConfig } from "./config";

const SECRET = "s".repeat(32);

describe("readDashboardConfig", () => {
  it("reads the admin API URL and the session secret", () => {
    const config = readDashboardConfig({
      ADMIN_API_URL: "http://admin-api:8001",
      DASHBOARD_SESSION_SECRET: SECRET,
    });

    expect(config).toEqual({
      adminApiUrl: "http://admin-api:8001",
      sessionSecret: SECRET,
    });
  });

  it("removes a trailing slash from the admin API URL", () => {
    const config = readDashboardConfig({
      ADMIN_API_URL: "http://localhost:8001/",
      DASHBOARD_SESSION_SECRET: SECRET,
    });

    expect(config.adminApiUrl).toBe("http://localhost:8001");
  });

  it("refuses a missing session secret", () => {
    expect(() =>
      readDashboardConfig({ ADMIN_API_URL: "http://admin-api:8001" }),
    ).toThrow(/DASHBOARD_SESSION_SECRET is missing/);
  });

  it("refuses a session secret shorter than 32 characters", () => {
    expect(() =>
      readDashboardConfig({
        ADMIN_API_URL: "http://admin-api:8001",
        DASHBOARD_SESSION_SECRET: "s".repeat(31),
      }),
    ).toThrow(/at least 32 characters/);
  });

  it("refuses a missing admin API URL: there is no default", () => {
    expect(() =>
      readDashboardConfig({ DASHBOARD_SESSION_SECRET: SECRET }),
    ).toThrow(DashboardConfigError);
  });

  it("refuses an admin API URL that is not http or https", () => {
    expect(() =>
      readDashboardConfig({
        ADMIN_API_URL: "admin-api:8001",
        DASHBOARD_SESSION_SECRET: SECRET,
      }),
    ).toThrow(/ADMIN_API_URL/);
  });
});

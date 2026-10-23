// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdminAction, AdminActionPage } from "@/api/tenant-keys";
import type { LoadActionsResult } from "@/lib/key-actions";

import { ActionHistory, summarizeDetails } from "./action-history";

afterEach(cleanup);

function action(id: number, overrides: Partial<AdminAction> = {}): AdminAction {
  return {
    id,
    created_at: "2026-10-23T12:30:00Z",
    operator_id: 1,
    actor: "alice",
    action: "set-limits",
    target: "acme",
    details: { rpm: 30 },
    ...overrides,
  };
}

function loader(result: LoadActionsResult) {
  return vi.fn<(before: number) => Promise<LoadActionsResult>>(
    async () => result,
  );
}

function bodyRows() {
  const [, body] = screen.getAllByRole("rowgroup");
  return within(body).getAllByRole("row");
}

describe("ActionHistory", () => {
  it("shows one row per action: time, actor, action, target and details", () => {
    const page: AdminActionPage = {
      actions: [
        action(3, {
          action: "create-key",
          details: { key_id: 9, prefix: "gw_abcdef", rpm: 30 },
        }),
        action(2, {
          action: "revoke-key",
          target: "9",
          actor: "cli",
          operator_id: null,
          details: { tenant: "acme", prefix: "gw_abcdef" },
        }),
      ],
      next_before: null,
    };
    render(<ActionHistory firstPage={page} loadMore={loader({} as never)} />);

    const [first, second] = bodyRows();
    expect(first).toHaveTextContent("alice");
    expect(within(first).getByTitle("create-key")).toHaveTextContent(
      "Create key",
    );
    expect(first).toHaveTextContent("acme");
    expect(first).toHaveTextContent("key id 9, prefix gw_abcdef, rpm 30");
    expect(within(first).getByText(/2026/).tagName).toBe("TIME");
    expect(second).toHaveTextContent("cli");
    expect(second).toHaveTextContent("key 9");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("loads older actions with the cursor and adds them below", async () => {
    const loadMore = loader({
      status: "loaded",
      page: { actions: [action(1, { actor: "bob" })], next_before: null },
    });
    render(
      <ActionHistory
        firstPage={{ actions: [action(2)], next_before: 2 }}
        loadMore={loadMore}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(loadMore).toHaveBeenCalledWith(2);
    expect(bodyRows()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("shows an error when older actions cannot be loaded", async () => {
    render(
      <ActionHistory
        firstPage={{ actions: [action(2)], next_before: 2 }}
        loadMore={loader({
          status: "error",
          error: {
            kind: "api",
            status: 503,
            code: "database_unavailable",
            message: "The database is unavailable. Try again later.",
          },
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The database is unavailable.",
    );
    // The button is enabled again once the transition ends, a moment after the alert.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled(),
    );
  });

  it("says when there is no action yet", () => {
    render(
      <ActionHistory
        firstPage={{ actions: [], next_before: null }}
        loadMore={loader({} as never)}
      />,
    );

    expect(screen.getByText("No admin action yet.")).toBeInTheDocument();
  });
});

describe("summarizeDetails", () => {
  it("names a cache clear of every alias", () => {
    const clear = action(1, {
      action: "clear-cache",
      details: { alias: null, removed: 4 },
    });

    expect(summarizeDetails(clear, "en")).toBe("every alias, removed 4");
    expect(summarizeDetails(clear, "fr")).toBe("tous les alias, supprimées 4");
  });

  it("shows a detail it does not know with its raw name", () => {
    expect(
      summarizeDetails(action(1, { details: { brand_new: 2 } }), "fr"),
    ).toBe("brand new 2");
  });

  it("shows a dash when there is no detail", () => {
    expect(summarizeDetails(action(1, { details: {} }), "en")).toBe("-");
  });
});

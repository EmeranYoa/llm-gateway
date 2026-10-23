// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutoRefresh } from "./auto-refresh";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));

const NOW = new Date("2026-10-23T12:00:00Z");

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  router.refresh.mockReset();
  setVisibility("visible");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("AutoRefresh", () => {
  it("refreshes the page every 10 s and shows the age of the data", () => {
    render(
      <AutoRefresh updatedAt={NOW.toISOString()} dataKey="24h">
        <p>Data</p>
      </AutoRefresh>,
    );
    expect(screen.getByText("Data")).toBeInTheDocument();
    expect(screen.getByText("Updated 0 s ago")).toBeInTheDocument();

    advance(9_000);
    expect(router.refresh).not.toHaveBeenCalled();
    expect(screen.getByText("Updated 9 s ago")).toBeInTheDocument();

    advance(1_000);
    expect(router.refresh).toHaveBeenCalledTimes(1);
    advance(10_000);
    expect(router.refresh).toHaveBeenCalledTimes(2);
  });

  it("stops refreshing while paused, and starts again on resume", () => {
    render(
      <AutoRefresh updatedAt={NOW.toISOString()} dataKey="24h">
        <p>Data</p>
      </AutoRefresh>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Pause auto-refresh" }));
    advance(30_000);
    expect(router.refresh).not.toHaveBeenCalled();
    expect(screen.getByText("Auto-refresh paused")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Resume auto-refresh" }),
    );
    advance(10_000);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("stops refreshing while the tab is hidden", () => {
    render(
      <AutoRefresh updatedAt={NOW.toISOString()} dataKey="24h">
        <p>Data</p>
      </AutoRefresh>,
    );

    setVisibility("hidden");
    advance(30_000);
    expect(router.refresh).not.toHaveBeenCalled();

    setVisibility("visible");
    advance(10_000);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("keeps the last data and shows a badge when a refresh fails", () => {
    const { rerender } = render(
      <AutoRefresh updatedAt={NOW.toISOString()} dataKey="24h">
        <p>Data of 12:00</p>
      </AutoRefresh>,
    );
    expect(screen.queryByText("Update failed")).not.toBeInTheDocument();

    advance(10_000);
    rerender(
      <AutoRefresh updatedAt={null} dataKey="24h" failed>
        <p>The admin API cannot be reached.</p>
      </AutoRefresh>,
    );

    expect(screen.getByText("Data of 12:00")).toBeInTheDocument();
    expect(
      screen.queryByText("The admin API cannot be reached."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Update failed");
    expect(screen.getByText("Updated 10 s ago")).toBeInTheDocument();

    // The next refresh works again: new data, no badge.
    rerender(
      <AutoRefresh updatedAt={new Date().toISOString()} dataKey="24h">
        <p>Data of 12:00:10</p>
      </AutoRefresh>,
    );
    expect(screen.getByText("Data of 12:00:10")).toBeInTheDocument();
    expect(screen.queryByText("Update failed")).not.toBeInTheDocument();
  });

  it("shows the error when there is no earlier data for the same filters", () => {
    const { rerender } = render(
      <AutoRefresh updatedAt={NOW.toISOString()} dataKey="24h">
        <p>Data of 24h</p>
      </AutoRefresh>,
    );

    rerender(
      <AutoRefresh updatedAt={null} dataKey="7d" failed>
        <p>The admin API cannot be reached.</p>
      </AutoRefresh>,
    );

    expect(
      screen.getByText("The admin API cannot be reached."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Data of 24h")).not.toBeInTheDocument();
    expect(screen.queryByText("Update failed")).not.toBeInTheDocument();
  });
});

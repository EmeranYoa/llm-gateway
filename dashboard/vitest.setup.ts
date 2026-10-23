import "@testing-library/jest-dom/vitest";

import { vi } from "vitest";

// `server-only` throws when imported outside a React Server Components build.
// Tests import server modules directly, so it is replaced by an empty module.
vi.mock("server-only", () => ({}));

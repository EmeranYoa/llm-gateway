import "@testing-library/jest-dom/vitest";

import { vi } from "vitest";

// `server-only` throws when imported outside a React Server Components build.
// Tests import server modules directly, so it is replaced by an empty module.
vi.mock("server-only", () => ({}));

// Server pages read the language of the request with `next/headers`, which
// needs a request. Tests have none: an empty request gives English. A test can
// mock `next/headers` again to choose a language.
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
  headers: async () => new Headers(),
}));

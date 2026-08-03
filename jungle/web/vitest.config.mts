import { resolve } from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
      // `server-only` throws by design when imported outside a server component.
      // The guard is what we want in the app and noise in a unit test, so it is
      // stubbed here rather than removed from the source.
      "server-only": resolve(__dirname, "./src/lib/api/__tests__/server-only.stub.ts"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

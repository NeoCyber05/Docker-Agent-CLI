import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: false,
    environment: "node",
    include: ["src/**/__tests__/**/*.test.ts", "tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["**/__tests__/**", "src/entrypoints/cli.ts"],
    },
  },
  resolve: {
    alias: { src: new URL("./src", import.meta.url).pathname },
  },
});

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["src/test_setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

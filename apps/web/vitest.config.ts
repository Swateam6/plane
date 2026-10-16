import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
      "next/link": fileURLToPath(new URL("./app/compat/next/link.tsx", import.meta.url)),
    },
    dedupe: ["react", "react-dom"],
  },
  test: {
    projects: [
      { extends: true, test: { name: "unit", include: ["tests/**/*.test.ts"], environment: "node" } },
      {
        extends: true,
        test: {
          name: "dom",
          include: ["tests/**/*.test.tsx"],
          environment: "jsdom",
          setupFiles: ["./vitest.setup.ts"],
        },
      },
    ],
  },
});

import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/entrypoints/cli.ts"],
  format: ["esm"],
  target: "node20",
  outDir: "dist",
  bundle: true,
  clean: true,
  splitting: false,
  sourcemap: true,
  banner: { js: "#!/usr/bin/env node" },
});

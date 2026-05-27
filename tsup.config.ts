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
  onSuccess: "node -e \"require('fs').cpSync(require('path').join(process.cwd(),'src','prompts'),require('path').join(process.cwd(),'dist','prompts'),{recursive:true})\"",
});

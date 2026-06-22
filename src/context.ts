import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = path.join(here, "prompts");

// Eager-read at import: surfaces missing-file errors at startup, not mid-conversation.
const SYSTEM_PROMPT_TEMPLATE = fs.readFileSync(path.join(PROMPTS_DIR, "react.md"), "utf-8");

export function buildSystemPrompt(stateSummary: string): string {
  return SYSTEM_PROMPT_TEMPLATE.replace("{{STATE_SUMMARY}}", stateSummary.trim() || "(none)");
}

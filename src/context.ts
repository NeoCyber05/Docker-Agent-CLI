import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { QueryMode } from "./tools";

// Substring match is intentional per spec §7.2: the classifier is a hint, not a
// hard gate — plan_stack is exposed in both modes, so mis-routes self-correct.
const PLAN_KEYWORDS = ["tạo", "create", "deploy", "triển khai", "setup", "build a", "spin up"];

export function classifyIntent(text: string): QueryMode {
  const t = text.toLowerCase();
  if (PLAN_KEYWORDS.some((k) => t.includes(k))) return "plan-once";
  return "react";
}

const here = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = path.join(here, "prompts");

// Eager-read at import: surfaces missing-file errors at startup, not mid-conversation.
const TEMPLATES: Record<QueryMode, string> = {
  "plan-once": fs.readFileSync(path.join(PROMPTS_DIR, "planOnce.md"), "utf-8"),
  react: fs.readFileSync(path.join(PROMPTS_DIR, "react.md"), "utf-8"),
};

export function buildSystemPrompt(mode: QueryMode, stateSummary: string): string {
  return TEMPLATES[mode].replace("{{STATE_SUMMARY}}", stateSummary.trim() || "(none)");
}
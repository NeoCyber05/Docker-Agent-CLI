import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { QueryMode } from "./tools";

const PLAN_KEYWORDS = ["tạo", "create", "deploy", "triển khai", "setup", "build a", "spin up"];

export function classifyIntent(text: string): QueryMode {
  const t = text.toLowerCase();
  if (PLAN_KEYWORDS.some((k) => t.includes(k))) return "plan-once";
  return "react";
}

const here = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = path.join(here, "prompts");

function loadPromptTemplate(mode: QueryMode): string {
  const file = mode === "plan-once" ? "planOnce.md" : "react.md";
  return fs.readFileSync(path.join(PROMPTS_DIR, file), "utf-8");
}

export function buildSystemPrompt(mode: QueryMode, stateSummary: string): string {
  return loadPromptTemplate(mode).replace("{{STATE_SUMMARY}}", stateSummary.trim() || "(none)");
}

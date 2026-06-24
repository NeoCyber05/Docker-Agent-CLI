export interface ToolPresentation {
  title: string;
  summary: string;
  detailLines: string[];
}

const SECRET_PATTERN = /secret|token|password|apiKey|credential/i;
const MAX_DETAIL_LINES = 20;
const MAX_DETAIL_BYTES = 4096;

function maskSecrets(text: string): string {
  // Replace values that follow secret-like keys in JSON-like or key=value contexts.
  // Approach: find quoted strings or values after secret-like keys and mask them.
  // Simpler: replace any value after a secret-like key on the same line.
  return text
    .replace(
      /((?:--)?(?:secret|token|password|api[-_]?key|credential)[\w-]*(?:=|[ \t]+))["']?[^\s,"'}\]]+["']?/gi,
      "$1***",
    )
    .split("\n")
    .map((line) => {
      // Heuristic: if line contains a secret-like key, mask the value part.
      // For JSON: "key": "value" or 'key': 'value'
      // For plain: key=value
      if (!SECRET_PATTERN.test(line)) return line;
      // Mask values in JSON-like strings
      return line.replace(
        /(["']?(?:secret|token|password|apiKey|credential)[\w]*["']?\s*[:=]\s*)["']?[^\s,"'}\]]+["']?/gi,
        '$1"***"',
      );
    })
    .join("\n");
}

function sanitizeArgv(args: string[]): string[] {
  let maskNext = false;
  return args.map((arg) => {
    if (maskNext) {
      maskNext = false;
      return "***";
    }
    if (/^--?(?:secret|token|password|api[-_]?key|credential)(?:=|$)/i.test(arg)) {
      if (!arg.includes("=")) maskNext = true;
      return arg.includes("=") ? `${arg.slice(0, arg.indexOf("=") + 1)}***` : arg;
    }
    return arg;
  });
}

function truncateLines(lines: string[], maxLines: number, maxBytes: number): string[] {
  let trimmed = lines.slice(0, maxLines);
  let text = trimmed.join("\n");
  let bytes = Buffer.byteLength(text, "utf-8");
  while (bytes > maxBytes && trimmed.length > 0) {
    trimmed = trimmed.slice(0, -1);
    text = trimmed.join("\n");
    bytes = Buffer.byteLength(text, "utf-8");
  }
  // If still over maxBytes, truncate the last line itself.
  if (bytes > maxBytes && trimmed.length > 0) {
    const lastIndex = trimmed.length - 1;
    let last = trimmed[lastIndex] ?? "";
    while (
      Buffer.byteLength(last, "utf-8") >
        maxBytes - Buffer.byteLength(trimmed.slice(0, -1).join("\n"), "utf-8") &&
      last.length > 0
    ) {
      last = last.slice(0, -1);
    }
    trimmed[lastIndex] = `${last}…`;
  }
  return trimmed;
}

function toDetailLines(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  if (typeof value === "string") {
    return value.split("\n").filter((l) => l.length > 0);
  }
  if (typeof value !== "object") return [String(value)];
  // Structured rendering instead of raw JSON.stringify
  const lines: string[] = [];
  for (const [k, v] of Object.entries(value)) {
    if (v === undefined) continue;
    if (SECRET_PATTERN.test(k)) {
      lines.push(`${k}: ***`);
      continue;
    }
    if (typeof v === "string") {
      const splitted = v.split("\n");
      if (splitted.length === 1) {
        lines.push(`${k}: ${v}`);
      } else {
        lines.push(`${k}:`);
        for (const s of splitted.slice(0, 10)) {
          lines.push(`  ${s}`);
        }
        if (splitted.length > 10) lines.push(`  … (${splitted.length - 10} more lines)`);
      }
    } else if (Array.isArray(v)) {
      lines.push(`${k}: [${v.length} items]`);
      const values =
        k === "args" && v.every((item) => typeof item === "string")
          ? sanitizeArgv(v as string[])
          : v;
      for (const item of values.slice(0, 5)) {
        const itemLines = toDetailLines(item);
        for (const il of itemLines.slice(0, 3)) {
          lines.push(`  ${il}`);
        }
        if (itemLines.length > 3) lines.push("  …");
      }
      if (v.length > 5) lines.push(`  … (${v.length - 5} more items)`);
    } else if (typeof v === "object" && v !== null) {
      lines.push(`${k}:`);
      const nested = toDetailLines(v);
      for (const nl of nested.slice(0, 5)) {
        lines.push(`  ${nl}`);
      }
      if (nested.length > 5) lines.push("  …");
    } else {
      lines.push(`${k}: ${String(v)}`);
    }
  }
  return lines;
}

function buildDetail(input: unknown, output?: unknown): string[] {
  const inputLines = toDetailLines(input);
  const outputLines = output !== undefined ? toDetailLines(output) : [];
  const all = [
    ...(inputLines.length > 0 ? ["Input:", ...inputLines.map((l) => `  ${l}`)] : []),
    ...(outputLines.length > 0 ? ["Output:", ...outputLines.map((l) => `  ${l}`)] : []),
  ];
  return all;
}

export function sanitizeToolText(text: string): string {
  const masked = maskSecrets(text);
  const bytes = Buffer.byteLength(masked, "utf-8");
  if (bytes <= MAX_DETAIL_BYTES) return masked;
  // Truncate by bytes, reserving space for ellipsis
  const ellipsis = "…";
  const ellipsisBytes = Buffer.byteLength(ellipsis, "utf-8");
  let truncated = masked;
  while (
    Buffer.byteLength(truncated, "utf-8") + ellipsisBytes > MAX_DETAIL_BYTES &&
    truncated.length > 0
  ) {
    truncated = truncated.slice(0, -1);
  }
  return truncated + ellipsis;
}

export function presentTool(name: string, input: unknown, output?: unknown): ToolPresentation {
  let title = `Tool: ${name}`;
  let summary = `Run ${name}`;

  switch (name) {
    case "initialize_project_policy": {
      const typedInput = input as { reason?: string; path?: string; content?: string };
      const detailLines = [
        `Reason: ${typedInput.reason ?? ""}`,
        `Path: ${typedInput.path ?? ""}`,
        "",
        "Proposed Content:",
        ...(typedInput.content ?? "").split("\n").map((line) => `  ${line}`),
      ];
      return {
        title: "Initialize Project Policy",
        summary:
          "Create project-policies.yaml with default/empty configuration (respecting global policy)",
        detailLines,
      };
    }
    case "plan_stack": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      const intent = (input as Record<string, unknown>)?.intent ?? "";
      title = `Plan stack: ${stackName}`;
      summary = `Generate Compose plan for ${stackName}${intent ? ` (${intent})` : ""}`;
      break;
    }
    case "apply_stack": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      title = `Apply stack: ${stackName}`;
      summary = `Deploy stack ${stackName}`;
      break;
    }
    case "destroy_stack": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      const removeVolumes = (input as Record<string, unknown>)?.removeVolumes === true;
      title = `Destroy stack: ${stackName}`;
      summary = `Tear down stack ${stackName}${removeVolumes ? " (volumes removed)" : ""}`;
      break;
    }
    case "destroy_all_stacks": {
      title = "Destroy all stacks";
      summary = "Tear down all stacks";
      break;
    }
    case "list_stacks": {
      title = "List stacks";
      summary = "List all stacks";
      break;
    }
    case "inspect_drift": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      title = `Inspect drift: ${stackName}`;
      summary = `Compare desired vs actual for ${stackName}`;
      break;
    }
    case "remediate_drift": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      title = `Remediate drift: ${stackName}`;
      summary = `Detect drift and prepare remediation for ${stackName}`;
      break;
    }
    case "get_stack_status": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      title = `Stack status: ${stackName}`;
      summary = `Container state and logs for ${stackName}`;
      break;
    }
    case "get_logs": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      const service = (input as Record<string, unknown>)?.service;
      title = service ? `Logs: ${stackName}/${service}` : `Logs: ${stackName}`;
      summary = `Fetch logs for ${stackName}${service ? ` (service: ${service})` : ""}`;
      break;
    }
    case "get_health": {
      const stackName = (input as Record<string, unknown>)?.stackName ?? "unknown";
      title = `Health: ${stackName}`;
      summary = `Per-container health and stats for ${stackName}`;
      break;
    }
    case "pull_image": {
      const image = (input as Record<string, unknown>)?.image ?? "unknown";
      title = `Pull image: ${image}`;
      summary = `Validate and pull ${image}`;
      break;
    }
    case "exec_docker": {
      const args = (input as Record<string, unknown>)?.args as string[] | undefined;
      const cmd = args ? sanitizeArgv(args).join(" ") : "";
      title = `Docker: ${cmd}`;
      summary = `Run docker ${cmd}`;
      break;
    }
  }

  const detailLines = truncateLines(buildDetail(input, output), MAX_DETAIL_LINES, MAX_DETAIL_BYTES);
  const sanitizedDetail = detailLines.map((l) => sanitizeToolText(l));

  return {
    title: sanitizeToolText(title),
    summary: sanitizeToolText(summary),
    detailLines: sanitizedDetail,
  };
}

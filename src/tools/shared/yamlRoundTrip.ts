import { parseStackDefinition } from "src/state/StateStore";
import { parse as parseYaml } from "yaml";

export interface YamlRoundTripResult {
  ok: boolean;
  error?: string;
}

export function validateYamlRoundTrip(yaml: string): YamlRoundTripResult {
  if (!yaml.trim()) {
    return { ok: false, error: "empty YAML" };
  }

  let parsed: unknown;
  try {
    parsed = parseYaml(yaml);
  } catch (err) {
    return {
      ok: false,
      error: `YAML parse failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  try {
    parseStackDefinition(parsed, "<round-trip>");
  } catch (err) {
    return {
      ok: false,
      error: `schema validation failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  return { ok: true };
}

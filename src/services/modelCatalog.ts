import { PROVIDER_NAMES, type ProviderName, isValidProvider } from "src/config";
import type { Provider } from "src/services/api/types";
import type { ProviderStatus } from "src/services/providerStatus";

export type CatalogEntry =
  | { provider: ProviderName; connected: true; models: string[] }
  | { provider: ProviderName; connected: false; reason: string };

export type CatalogRow =
  | { kind: "header"; provider: ProviderName; connected: boolean }
  | { kind: "model"; provider: ProviderName; model: string }
  | { kind: "connect"; provider: ProviderName; reason: string };

const PROVIDER_LABELS: Record<ProviderName, string> = {
  gemini: "Gemini",
  openai: "OpenAI",
  ollama: "Ollama",
};

export function providerLabel(provider: ProviderName): string {
  return PROVIDER_LABELS[provider];
}

export function parseProviderModel(
  input: string,
  defaultProvider?: ProviderName,
): { provider: ProviderName; model: string } | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  const slashIndex = trimmed.indexOf("/");
  if (slashIndex >= 0) {
    const providerPart = trimmed.slice(0, slashIndex);
    const model = trimmed.slice(slashIndex + 1);
    if (!isValidProvider(providerPart) || !model) return null;
    return { provider: providerPart, model };
  }

  if (!defaultProvider) return null;
  return { provider: defaultProvider, model: trimmed };
}

export async function buildModelCatalog(
  statuses: ProviderStatus[],
  providers: Partial<Record<ProviderName, Provider>>,
): Promise<CatalogEntry[]> {
  const statusByProvider = new Map(statuses.map((s) => [s.provider, s]));

  return Promise.all(
    PROVIDER_NAMES.map(async (provider): Promise<CatalogEntry> => {
      const status = statusByProvider.get(provider);
      if (!status?.connected) {
        return {
          provider,
          connected: false,
          reason: status?.reason ?? "Not connected",
        };
      }

      const instance = providers[provider];
      if (!instance || typeof instance.listModels !== "function") {
        return { provider, connected: true, models: [] };
      }

      const models = await instance.listModels();
      return { provider, connected: true, models };
    }),
  );
}

export function flattenCatalog(catalog: CatalogEntry[]): CatalogRow[] {
  const rows: CatalogRow[] = [];
  for (const entry of catalog) {
    rows.push({ kind: "header", provider: entry.provider, connected: entry.connected });
    if (entry.connected) {
      for (const model of entry.models) {
        rows.push({ kind: "model", provider: entry.provider, model });
      }
    } else {
      rows.push({ kind: "connect", provider: entry.provider, reason: entry.reason });
    }
  }
  return rows;
}

export function filterRows(rows: CatalogRow[], query: string): CatalogRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;

  const providersWithMatches = new Set<ProviderName>();
  const matchingRows: CatalogRow[] = [];

  for (const row of rows) {
    if (row.kind === "header") continue;
    const label = providerLabel(row.provider).toLowerCase();
    const haystack = row.kind === "model" ? `${label} ${row.model}`.toLowerCase() : label;
    if (haystack.includes(q)) {
      providersWithMatches.add(row.provider);
      matchingRows.push(row);
    }
  }

  const result: CatalogRow[] = [];
  for (const provider of PROVIDER_NAMES) {
    if (!providersWithMatches.has(provider)) continue;
    const header = rows.find(
      (r): r is Extract<CatalogRow, { kind: "header" }> =>
        r.kind === "header" && r.provider === provider,
    );
    if (header) result.push(header);
    for (const row of matchingRows) {
      if (row.provider === provider) result.push(row);
    }
  }
  return result;
}

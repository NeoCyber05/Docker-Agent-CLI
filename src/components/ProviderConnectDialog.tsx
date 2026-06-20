import { Box, Text, useInput } from "ink";
import type React from "react";
import { useMemo, useState } from "react";
import type { ProviderName } from "src/config";
import { type ApiKeyStatus, isApiKeyProviderName } from "src/secrets/apiKeyStore";

/** Compatible with `ProviderStatus` from `src/services/providerStatus` when present. */
export interface ProviderStatus {
  provider: ProviderName;
  connected: boolean;
  reason?: string;
  modelCount?: number;
}

export const PROVIDER_CONNECT_META: Record<
  ProviderName,
  { title: string; description: string; category: string }
> = {
  gemini: { title: "Gemini", description: "(API key)", category: "Popular" },
  openai: { title: "OpenAI", description: "(API key)", category: "Popular" },
  openrouter: { title: "OpenRouter", description: "(API key)", category: "Popular" },
  ollama: { title: "Ollama", description: "(local)", category: "Providers" },
};

const PROVIDER_ORDER: ProviderName[] = ["gemini", "openai", "openrouter", "ollama"];

const CATEGORY_ORDER = ["Popular", "Providers"] as const;

export interface ProviderConnectOption {
  provider: ProviderName;
  title: string;
  description: string;
  category: string;
  connected: boolean;
  keySource?: "env" | "saved";
}

export function buildProviderConnectOptions(
  statuses: ProviderStatus[],
  apiKeyStatuses: ApiKeyStatus[] = [],
): ProviderConnectOption[] {
  const statusByProvider = new Map(statuses.map((s) => [s.provider, s]));
  const keyByProvider = new Map(apiKeyStatuses.map((s) => [s.provider, s]));
  return PROVIDER_ORDER.map((provider) => {
    const meta = PROVIDER_CONNECT_META[provider];
    const status = statusByProvider.get(provider);
    const keyStatus = isApiKeyProviderName(provider) ? keyByProvider.get(provider) : undefined;
    return {
      provider,
      title: meta.title,
      description: meta.description,
      category: meta.category,
      connected: status?.connected ?? false,
      ...(keyStatus?.state === "set" && keyStatus.source ? { keySource: keyStatus.source } : {}),
    };
  });
}

type DisplayRow =
  | { kind: "category"; label: string }
  | { kind: "provider"; option: ProviderConnectOption; selectableIndex: number };

function buildDisplayRows(options: ProviderConnectOption[]): DisplayRow[] {
  const rows: DisplayRow[] = [];
  let selectableIndex = 0;
  for (const category of CATEGORY_ORDER) {
    const inCategory = options.filter((o) => o.category === category);
    if (inCategory.length === 0) continue;
    rows.push({ kind: "category", label: category });
    for (const option of inCategory) {
      rows.push({ kind: "provider", option, selectableIndex: selectableIndex++ });
    }
  }
  return rows;
}

export function ProviderConnectDialog({
  statuses,
  apiKeyStatuses = [],
  onSelect,
  onCancel,
}: {
  statuses: ProviderStatus[];
  apiKeyStatuses?: ApiKeyStatus[];
  onSelect: (provider: ProviderName, meta: { connected: boolean }) => void;
  onCancel: () => void;
}): React.ReactElement {
  const options = useMemo(
    () => buildProviderConnectOptions(statuses, apiKeyStatuses),
    [statuses, apiKeyStatuses],
  );
  const displayRows = useMemo(() => buildDisplayRows(options), [options]);
  const [index, setIndex] = useState(0);

  useInput((_char, key) => {
    if (key.upArrow) {
      setIndex((i) => (i - 1 + options.length) % options.length);
    } else if (key.downArrow) {
      setIndex((i) => (i + 1) % options.length);
    } else if (key.return) {
      const choice = options[index];
      if (choice) onSelect(choice.provider, { connected: choice.connected });
    } else if (key.escape) {
      onCancel();
    }
  });

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      marginY={1}
      overflowX="hidden"
    >
      <Text bold color="cyan">
        Connect a provider
      </Text>
      <Box marginTop={1} flexDirection="column">
        {displayRows.map((row) => {
          if (row.kind === "category") {
            return (
              <Text key={`cat-${row.label}`} bold dimColor>
                {row.label}
              </Text>
            );
          }
          const { option, selectableIndex } = row;
          const selected = selectableIndex === index;
          return (
            <Text
              key={option.provider}
              {...(selected ? { color: "black", backgroundColor: "cyan" } : {})}
            >
              {selected ? "❯ " : "  "}
              {option.connected ? <Text color="green">✓ </Text> : "  "}
              <Text bold={selected}>{option.title}</Text>
              <Text dimColor> {option.description}</Text>
              {option.keySource && <Text dimColor> · {option.keySource}</Text>}
            </Text>
          );
        })}
      </Box>
      <Box marginTop={1}>
        <Text bold>[↑/↓] navigate [Enter] select [Esc] cancel</Text>
      </Box>
    </Box>
  );
}

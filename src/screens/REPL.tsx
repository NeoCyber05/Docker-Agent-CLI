import fs from "node:fs";
import path from "node:path";
import { Box, Text, useApp, useInput, useStdin, useStdout } from "ink";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PermissionResponse } from "src/types/permissions";
import type { StackDiff } from "src/types/stack";
import { QueryEngine, type QueryEngineDeps } from "../QueryEngine";
import { createDefaultRegistry } from "../commands/registry";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { ApiKeyInputDialog } from "../components/ApiKeyInputDialog";
import { CommandPalette } from "../components/CommandPalette";
import { Footer } from "../components/Footer";
import { LogPane } from "../components/LogPane";
import { ModelPickerDialog } from "../components/ModelPickerDialog";
import { OllamaSetupDialog } from "../components/OllamaSetupDialog";
import { PermissionDialog } from "../components/PermissionDialog";
import { PlanPreview } from "../components/PlanPreview";
import { PromptInput } from "../components/PromptInput";
import { ProviderConnectDialog } from "../components/ProviderConnectDialog";
import { QueuePanel } from "../components/QueuePanel";
import { SecretsInputDialog } from "../components/SecretsInputDialog";
import { ThinkingIndicator } from "../components/ThinkingIndicator";
import { ToolDetailsPanel } from "../components/ToolDetailsPanel";
import { TypedConfirmDialog } from "../components/TypedConfirmDialog";
import { WelcomeBanner } from "../components/WelcomeBanner";
import { PROVIDER_NAMES, stackStateYamlPath, type ProviderName } from "../config";
import {
  type ApiKeyProviderName,
  type ApiKeyStatus,
  type ApiKeyStore,
  apiKeyEnvVar,
  createApiKeyStore,
  describeApiKeyStatus,
  isApiKeyProviderName,
} from "../secrets/apiKeyStore";
import { resolveProviderForRequest } from "../services/api";
import type { Provider } from "../services/api/types";
import { type CatalogRow, buildModelCatalog, flattenCatalog } from "../services/modelCatalog";
import { type ProviderStatus, getProviderStatuses } from "../services/providerStatus";
import { routeSlashCommand } from "../slashRouter";
import { type SessionStore, sessionCwdMismatchWarning } from "../state/SessionStore";
import { StructuredLogger } from "../state/logger";
import { scrubLine } from "../state/secretRedactor";
import { collectSecretKeys } from "../tools/shared/secretKeys";
import type { ToolActivity } from "../ui/activity";
import { applySlashEffects } from "./applySlashEffects";
import { useInteractionSession } from "./useInteractionSession";

type LocalPending =
  | { kind: "apiKey"; provider: ApiKeyProviderName; returnTo?: "modelPicker" | "connect" }
  | { kind: "modelPicker"; rows: CatalogRow[] }
  | { kind: "providerConnect"; statuses: ProviderStatus[]; apiKeyStatuses: ApiKeyStatus[] }
  | { kind: "ollamaSetup"; host: string };

const DESTRUCTIVE_TOOLS = new Set(["apply_stack", "destroy_stack", "destroy_all_stacks"]);

const COMPACT_WELCOME_MAX_ROWS = 16;
const COMPACT_WELCOME_MAX_COLUMNS = 84;

function safeFrameWidth(stdout: NodeJS.WriteStream): number {
  return Math.max(1, (stdout.columns || 80) - 1);
}

function useSafeFrameWidth(): number {
  const { stdout } = useStdout();
  const [width, setWidth] = useState(() => safeFrameWidth(stdout));

  useEffect(() => {
    const onResize = () => setWidth(safeFrameWidth(stdout));
    stdout.on("resize", onResize);
    return () => {
      stdout.off("resize", onResize);
    };
  }, [stdout]);

  return width;
}

export function REPL({
  deps,
  version,
  resumedRecord,
  showBanner = true,
}: {
  deps: QueryEngineDeps & { providerName: string; yes?: boolean; apiKeyStore?: ApiKeyStore };
  version: string;
  resumedRecord?: import("../state/SessionStore").SessionRecord;
  showBanner?: boolean;
}): React.ReactElement {
  const resumeWarning = useMemo(
    () => (resumedRecord ? sessionCwdMismatchWarning(resumedRecord, deps.cwd) : undefined),
    [resumedRecord, deps.cwd],
  );
  const engine = useMemo(() => {
    const next = new QueryEngine(deps);
    if (resumedRecord) next.loadSession(resumedRecord);
    const logDir = path.join(deps.cwd, ".docker-agent", "logs");
    next.setLogger(new StructuredLogger(logDir, next.sessionId));
    return next;
  }, [deps, resumedRecord]);
  const apiKeyStore = useMemo(() => deps.apiKeyStore ?? createApiKeyStore(), [deps.apiKeyStore]);
  const session = useInteractionSession(engine, resumedRecord?.messages);

  useEffect(() => {
    if (!resumeWarning) return;
    session.dispatchActivity({ type: "assistant_text", delta: resumeWarning });
  }, [resumeWarning, session]);
  const latestTool = [...session.activities]
    .reverse()
    .find((activity): activity is ToolActivity => activity.type === "tool");
  const activeTool = session.activities.find(
    (activity): activity is ToolActivity =>
      activity.type === "tool" && activity.id === session.activeToolActivityId,
  );

  const [localPending, setLocalPending] = useState<LocalPending | null>(null);
  const [activeLogPane, setActiveLogPane] = useState<{
    stackName: string;
    service?: string;
    controller: AbortController;
  } | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const logControllerRef = useRef<AbortController | null>(null);

  const [showDetails, setShowDetails] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState<{
    requestId: number;
    text: string;
  } | null>(null);

  const [activeProviderName, setActiveProviderName] = useState(deps.providerName);
  const [activeModel, setActiveModel] = useState<string | undefined>(
    resumedRecord?.model ?? deps.model,
  );
  const [timelineKey, setTimelineKey] = useState(0);
  const { exit } = useApp();
  const frameWidth = useSafeFrameWidth();
  const { stdout } = useStdout();
  const compact =
    (stdout.rows || 24) <= COMPACT_WELCOME_MAX_ROWS || frameWidth < COMPACT_WELCOME_MAX_COLUMNS;

  const LOG_RING_MAX = 200;

  const stopLogPane = () => {
    logControllerRef.current?.abort();
    logControllerRef.current = null;
    setActiveLogPane(null);
    setLogLines([]);
  };

  const startLogPane = (stackName: string, service?: string) => {
    const yamlPath = stackStateYamlPath(deps.cwd, stackName);
    if (!fs.existsSync(yamlPath)) {
      session.dispatchActivity({
        type: "user_text",
        text: `/logs ${stackName}${service ? ` ${service}` : ""}`,
      });
      session.dispatchActivity({ type: "error", error: new Error(`stack ${stackName} not found`) });
      return;
    }
    logControllerRef.current?.abort();
    const controller = new AbortController();
    logControllerRef.current = controller;
    setLogLines([]);
    setActiveLogPane({ stackName, controller, ...(service ? { service } : {}) });

    const secretKeys = collectSecretKeys(stackName, {
      cwd: deps.cwd,
      stateStore: deps.stateStore,
    });
    const bound = deps.composeRunner.forStack(stackName, yamlPath);
    void (async () => {
      try {
        for await (const chunk of bound.logs({
          follow: true,
          tailLines: 50,
          signal: controller.signal,
          ...(service ? { service } : {}),
        })) {
          if (controller.signal.aborted) break;
          const scrubbed = scrubLine(chunk, secretKeys);
          setLogLines((prev) => {
            const next = [...prev, scrubbed];
            return next.length > LOG_RING_MAX ? next.slice(-LOG_RING_MAX) : next;
          });
        }
      } catch {
        /* generator ended or aborted */
      }
    })();
  };

  useEffect(() => {
    return () => {
      logControllerRef.current?.abort();
      logControllerRef.current = null;
    };
  }, []);

  const { setRawMode, isRawModeSupported } = useStdin();
  useEffect(() => {
    if (!isRawModeSupported) return;
    setRawMode(true);
    return () => setRawMode(false);
  }, [isRawModeSupported, setRawMode]);

  // Global key routing
  useInput((input, key) => {
    if (key.ctrl && input === "c") {
      if (activeLogPane) stopLogPane();
      else if (localPending) setLocalPending(null);
      else session.cancelCurrent();
      return;
    }
    if (session.pendingEvent || localPending || activeLogPane) return;
    if (key.ctrl && input === "o") {
      if (!latestTool) return;
      setShowPalette(false);
      setShowQueue(false);
      setShowDetails((v) => !v);
      return;
    }
    if (key.ctrl && input === "p") {
      setShowDetails(false);
      setShowQueue(false);
      setShowPalette((v) => !v);
      return;
    }
    if (key.ctrl && input === "q") {
      setShowDetails(false);
      setShowPalette(false);
      setShowQueue((v) => !v);
      return;
    }
  });

  const resolveAllProviders = (): Record<ProviderName, Provider> =>
    Object.fromEntries(
      PROVIDER_NAMES.map((name) => [
        name,
        resolveProviderForRequest(name, process.env, { apiKeyStore }),
      ]),
    ) as Record<ProviderName, Provider>;

  const openProviderConnect = async () => {
    const instances = resolveAllProviders();
    const statuses = await getProviderStatuses({ apiKeyStore, providers: instances });
    const apiKeyStatuses = await describeApiKeyStatus(apiKeyStore, process.env);
    setLocalPending({ kind: "providerConnect", statuses, apiKeyStatuses });
  };

  const openModelPicker = async (scopeProvider?: ProviderName) => {
    const instances = resolveAllProviders();
    const statuses = await getProviderStatuses({ apiKeyStore, providers: instances });
    const catalog = await buildModelCatalog(statuses, instances);
    let rows = flattenCatalog(catalog);
    if (scopeProvider) {
      rows = rows.filter(
        (r) =>
          (r.kind === "header" && r.provider === scopeProvider) ||
          (r.kind !== "header" && r.provider === scopeProvider),
      );
    }
    const hasNavigable = rows.some((r) => r.kind === "model" || r.kind === "connect");
    if (!hasNavigable) {
      session.dispatchActivity({
        type: "error",
        error: new Error("No providers connected. Use /connect first."),
      });
      const apiKeyStatuses = await describeApiKeyStatus(apiKeyStore, process.env);
      setLocalPending({ kind: "providerConnect", statuses, apiKeyStatuses });
      return;
    }
    setLocalPending({ kind: "modelPicker", rows });
  };

  const onModelPicked = (choice: { provider: ProviderName; model: string }) => {
    engine.provider = resolveProviderForRequest(choice.provider, process.env, { apiKeyStore });
    engine.model = choice.model;
    setActiveProviderName(choice.provider);
    setActiveModel(choice.model);
    setLocalPending(null);
    session.dispatchActivity({
      type: "assistant_text",
      delta: `Model set to ${choice.model} (${choice.provider})`,
    });
  };

  const onConnectProvider = (provider?: ProviderName) => {
    if (provider && isApiKeyProviderName(provider)) {
      setLocalPending({ kind: "apiKey", provider, returnTo: "modelPicker" });
      return;
    }
    if (provider === "ollama") {
      setLocalPending({
        kind: "ollamaSetup",
        host: process.env.OLLAMA_HOST ?? "http://localhost:11434",
      });
      return;
    }
    void openProviderConnect();
  };

  const handleSubmit = async (input: string) => {
    const targetPrompt = input.trim();
    const lowered = targetPrompt.toLowerCase();
    if (lowered === "exit" || lowered === "/exit") {
      session.cancelCurrent();
      setImmediate(() => setImmediate(() => setImmediate(() => exit())));
      return;
    }
    if (targetPrompt.startsWith("/")) {
      const result = await routeSlashCommand(input, {
        cwd: deps.cwd,
        stateStore: deps.stateStore,
        ...(deps.sessionStore ? { sessionStore: deps.sessionStore } : {}),
        activeProviderName: activeProviderName as ProviderName,
        apiKeyStore,
      });
      await applySlashEffects(result.effects, {
        input,
        session,
        engine,
        apiKeyStore,
        ...(deps.sessionStore ? { sessionStore: deps.sessionStore } : {}),
        exit,
        stopLogPane,
        setShowDetails,
        setShowPalette,
        setShowQueue,
        setTimelineKey,
        setActiveProviderName,
        setActiveModel,
        openProviderConnect,
        openModelPicker,
        startLogPane,
      });
      if (result.handled) return;
    }

    session.submit(targetPrompt);
  };

  const handleAnswer = (answer: PermissionResponse) => {
    if (session.pendingEvent) {
      if (
        session.pendingEvent.type === "permission_request" ||
        session.pendingEvent.type === "plan_ready" ||
        session.pendingEvent.type === "typed_confirm_request" ||
        session.pendingEvent.type === "secrets_input_request"
      ) {
        session.respond(session.pendingEvent.id, answer);
      }
    }
  };

  useEffect(() => {
    if (deps.yes && session.pendingEvent?.type === "permission_request") {
      session.respond(session.pendingEvent.id, { kind: "approve" });
    }
  }, [deps.yes, session.pendingEvent, session.respond]);

  const onApiKeySubmit = async (provider: ApiKeyProviderName, value: string) => {
    const returnTo = localPending?.kind === "apiKey" ? localPending.returnTo : undefined;
    try {
      await apiKeyStore.set(provider, value);
      process.env[apiKeyEnvVar(provider)] = value;
      setLocalPending(null);
      session.dispatchActivity({ type: "assistant_text", delta: `API key saved for ${provider}` });
      if (returnTo === "modelPicker") {
        await openModelPicker(provider);
      }
    } catch (err) {
      setLocalPending(null);
      session.dispatchActivity({
        type: "error",
        error: err instanceof Error ? err : new Error(String(err)),
      });
    }
  };

  const paletteCommands = useMemo(() => {
    const registry = createDefaultRegistry();
    registry.register({
      id: "cancel",
      title: "Cancel",
      description: "Cancel current turn",
      shortcut: "Ctrl+C",
      action: () => session.cancelCurrent(),
    });
    registry.register({
      id: "details",
      title: "Details",
      description: "Open latest tool details",
      shortcut: "Ctrl+O",
      action: () => setShowDetails(true),
    });
    registry.register({
      id: "queue-panel",
      title: "Queue",
      description: "Show queue panel",
      shortcut: "Ctrl+Q",
      action: () => setShowQueue(true),
    });
    registry.register({
      id: "clear",
      title: "Clear",
      description: "Clear chat history",
      action: () => {
        session.reset();
      },
    });
    return registry.getAll();
  }, [session]);

  const isInputBlocked =
    session.pendingEvent !== null ||
    localPending !== null ||
    showPalette ||
    showQueue ||
    (showDetails && latestTool !== undefined);

  return (
    <Box flexDirection="column" width={frameWidth} overflowX="hidden">
      {showBanner && (
        <WelcomeBanner
          version={version}
          provider={activeProviderName}
          {...(activeModel ? { model: activeModel } : {})}
          compact={compact}
        />
      )}
      {!showBanner && (
        <Box paddingX={1} overflowX="hidden">
          <Text>
            docker-agent | provider: <Text color="yellow">{activeProviderName}</Text>
            {" | "}
            model: <Text color="yellow">{activeModel ?? "default"}</Text>
          </Text>
        </Box>
      )}
      <ActivityTimeline
        key={timelineKey}
        items={session.activities}
        activeToolActivityId={session.activeToolActivityId}
      />
      {session.pendingEvent?.type === "permission_request" && (
        <PermissionDialog
          tool={session.pendingEvent.tool}
          input={session.pendingEvent.input}
          onAnswer={handleAnswer}
        />
      )}
      {session.pendingEvent?.type === "plan_ready" && (
        <PlanPreview
          composeYaml={session.pendingEvent.composeYaml}
          diff={session.pendingEvent.diff}
          {...(session.pendingEvent.autoGeneratedSecrets
            ? { autoGeneratedSecrets: session.pendingEvent.autoGeneratedSecrets }
            : {})}
          {...(session.pendingEvent.configFiles
            ? { configFiles: session.pendingEvent.configFiles }
            : {})}
          onAnswer={handleAnswer}
        />
      )}
      {session.pendingEvent?.type === "typed_confirm_request" && (
        <TypedConfirmDialog
          phrase={session.pendingEvent.phrase}
          reason={session.pendingEvent.reason}
          onAnswer={handleAnswer}
        />
      )}
      {session.pendingEvent?.type === "secrets_input_request" && (
        <SecretsInputDialog
          service={session.pendingEvent.service}
          keys={session.pendingEvent.keys}
          reason={session.pendingEvent.reason}
          onAnswer={handleAnswer}
        />
      )}
      {localPending?.kind === "apiKey" && (
        <ApiKeyInputDialog
          provider={localPending.provider}
          envVarName={apiKeyEnvVar(localPending.provider)}
          onSubmit={(value) => void onApiKeySubmit(localPending.provider, value)}
          onCancel={() => {
            setLocalPending(null);
            session.dispatchActivity({ type: "assistant_text", delta: "API key setup cancelled" });
          }}
        />
      )}
      {localPending?.kind === "providerConnect" && (
        <ProviderConnectDialog
          statuses={localPending.statuses}
          apiKeyStatuses={localPending.apiKeyStatuses}
          onSelect={(provider, { connected }) => {
            if (connected) void openModelPicker(provider);
            else onConnectProvider(provider);
          }}
          onCancel={() => setLocalPending(null)}
        />
      )}
      {localPending?.kind === "ollamaSetup" && (
        <OllamaSetupDialog
          host={localPending.host}
          onRetry={() => void openProviderConnect()}
          onCancel={() => setLocalPending(null)}
        />
      )}
      {localPending?.kind === "modelPicker" && (
        <ModelPickerDialog
          rows={localPending.rows}
          current={{ provider: activeProviderName as ProviderName, model: activeModel ?? "" }}
          onSelect={onModelPicked}
          onConnectProvider={onConnectProvider}
          onCancel={() => {
            setLocalPending(null);
            session.dispatchActivity({
              type: "assistant_text",
              delta: "Model selection cancelled",
            });
          }}
        />
      )}
      {activeLogPane && (
        <LogPane
          stackName={activeLogPane.stackName}
          {...(activeLogPane.service ? { service: activeLogPane.service } : {})}
          lines={logLines}
          onClose={stopLogPane}
        />
      )}
      {showDetails && latestTool && <ToolDetailsPanel activity={latestTool} />}
      {showPalette && (
        <CommandPalette
          commands={paletteCommands}
          onSelect={(cmd) => {
            if (cmd.action) cmd.action();
            else if (cmd.insertText) {
              setComposerPrefill((previous) => ({
                requestId: (previous?.requestId ?? 0) + 1,
                text: cmd.insertText ?? "",
              }));
            }
            setShowPalette(false);
          }}
          onClose={() => setShowPalette(false)}
        />
      )}
      {showQueue && (
        <QueuePanel
          queue={session.queue}
          onRemove={session.removeQueued}
          onClear={session.clearQueue}
          onResume={session.resumeQueue}
          onClose={() => setShowQueue(false)}
        />
      )}
      {!isInputBlocked && !activeLogPane && (
        <PromptInput
          onSubmit={(value) => void handleSubmit(value)}
          onResumeQueue={session.resumeQueue}
          phase={session.phase}
          {...(composerPrefill ? { prefill: composerPrefill } : {})}
        />
      )}
      {session.phase === "running" && !isInputBlocked && !activeLogPane && (
        <Box paddingLeft={1} marginY={1}>
          <ThinkingIndicator />
        </Box>
      )}
      <Footer
        usage={engine.totalUsage}
        sessionId={engine.sessionId}
        activeTool={activeTool?.title}
        queueCount={session.queue.length}
      />
    </Box>
  );
}

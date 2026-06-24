import type { QueryEngine } from "src/QueryEngine";
import type { ProviderName } from "src/config";
import type { ApiKeyStore } from "src/secrets/apiKeyStore";
import { resolveProviderForRequest } from "src/services/api";
import type { SlashEffect } from "src/slashRouter";
import type { SessionStore } from "src/state/SessionStore";
import type { useInteractionSession } from "./useInteractionSession";

type InteractionSession = ReturnType<typeof useInteractionSession>;

export interface SlashEffectApplierDeps {
  input: string;
  session: InteractionSession;
  engine: QueryEngine;
  apiKeyStore: ApiKeyStore;
  sessionStore?: SessionStore;
  exit: () => void;
  stopLogPane: () => void;
  setShowDetails: (value: boolean | ((prev: boolean) => boolean)) => void;
  setShowPalette: (value: boolean) => void;
  setShowQueue: (value: boolean) => void;
  setTimelineKey: (value: number | ((prev: number) => number)) => void;
  setActiveProviderName: (name: ProviderName) => void;
  setActiveModel: (model: string) => void;
  openProviderConnect: () => Promise<void>;
  openModelPicker: (scopeProvider?: ProviderName) => Promise<void>;
  startLogPane: (stackName: string, service?: string) => void;
}

export async function applySlashEffects(
  effects: SlashEffect[],
  deps: SlashEffectApplierDeps,
): Promise<void> {
  for (const effect of effects) {
    switch (effect.type) {
      case "emit_user_text":
        deps.session.dispatchActivity({ type: "user_text", text: effect.text });
        break;
      case "emit_assistant_text":
        deps.session.dispatchActivity({ type: "assistant_text", delta: effect.delta });
        break;
      case "emit_error":
        deps.session.dispatchActivity({ type: "error", error: new Error(effect.message) });
        break;
      case "submit_prompt":
        deps.session.submit(effect.prompt);
        break;
      case "exit":
        deps.session.cancelCurrent();
        deps.stopLogPane();
        deps.exit();
        break;
      case "clear_session":
        deps.stopLogPane();
        deps.setShowDetails(false);
        deps.setShowPalette(false);
        deps.setShowQueue(false);
        deps.session.reset();
        deps.setTimelineKey((k) => k + 1);
        break;
      case "open_provider_connect":
        await deps.openProviderConnect();
        break;
      case "open_model_picker":
        await deps.openModelPicker(effect.scopeProvider);
        break;
      case "set_model":
        deps.engine.provider = resolveProviderForRequest(effect.provider, process.env, {
          apiKeyStore: deps.apiKeyStore,
        });
        deps.engine.model = effect.model;
        deps.setActiveProviderName(effect.provider);
        deps.setActiveModel(effect.model);
        break;
      case "load_session": {
        const store = deps.sessionStore;
        if (!store) {
          deps.session.dispatchActivity({ type: "user_text", text: deps.input });
          deps.session.dispatchActivity({
            type: "error",
            error: new Error("Session persistence not configured."),
          });
          break;
        }
        const rec = effect.sessionId ? store.read(effect.sessionId) : store.latest();
        if (!rec) {
          deps.session.dispatchActivity({ type: "user_text", text: deps.input });
          deps.session.dispatchActivity({
            type: "error",
            error: new Error(
              effect.sessionId
                ? `Session "${effect.sessionId}" not found.`
                : "No previous session found to resume.",
            ),
          });
          break;
        }
        const warning = deps.engine.loadSession(rec);
        if (warning) {
          deps.session.dispatchActivity({ type: "assistant_text", delta: warning });
        }
        if (rec.model !== undefined) {
          deps.setActiveModel(rec.model);
        }
        deps.session.replaceActivities(deps.engine.getMessages());
        break;
      }
      case "start_log_pane":
        deps.startLogPane(effect.stackName, effect.service);
        break;
    }
  }
}

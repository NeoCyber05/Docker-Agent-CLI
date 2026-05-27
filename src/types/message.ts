export interface UserMessage {
  role: "user";
  content: string;
}

export type AssistantBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: unknown };

export interface AssistantMessage {
  role: "assistant";
  content: AssistantBlock[];
}

export interface ToolResultMessage {
  role: "tool";
  toolUseId: string;
  content: string;
  isError: boolean;
}

export type Message = UserMessage | AssistantMessage | ToolResultMessage;

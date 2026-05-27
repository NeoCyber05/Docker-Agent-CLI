export type PermissionResponse =
  | { kind: "approve" }
  | { kind: "deny" }
  | { kind: "always_allow_in_session" }
  | { kind: "typed_confirm_value"; value: string }
  | { kind: "secrets_input_values"; values: Record<string, string> };

export interface PermissionRequest {
  tool: string;
  input: unknown;
}

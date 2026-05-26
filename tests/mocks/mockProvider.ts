import type { ProviderEvent } from "src/services/api/types";

export interface ProviderScript {
  events: ProviderEvent[];
}

export class MockProvider {
  constructor(private script: ProviderScript) {}
  async *stream(_params: unknown): AsyncGenerator<ProviderEvent> {
    for (const ev of this.script.events) yield ev;
  }
}

export function replayProvider(script: ProviderScript): MockProvider {
  return new MockProvider(script);
}

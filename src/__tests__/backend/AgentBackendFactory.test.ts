import { describe, expect, test } from "vitest";
import { createBackend, type AgentBackend } from "src/backend/AgentBackend";

describe("createBackend", () => {
  test("returns CurrentBackend by default", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    delete process.env.DOCKER_AGENT_BACKEND;
    const b = createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test.skip("returns LangGraphBackend when DOCKER_AGENT_BACKEND=langgraph", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "langgraph";
    const b = createBackend();
    expect(b.name).toBe("langgraph");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test("falls back to current on unknown value", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "bogus";
    const b = createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });
});

describe("AgentBackend interface typing", () => {
  test("AgentBackend has name and query method", () => {
    const b: AgentBackend = {
      name: "stub",
      query: async function* () {},
    };
    expect(b.name).toBe("stub");
  });
});

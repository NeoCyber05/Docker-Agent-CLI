import { type AgentBackend, createBackend } from "src/backend/AgentBackend";
import { describe, expect, test } from "vitest";

describe("createBackend", () => {
  test("returns CurrentBackend by default", async () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = undefined;
    const b = await createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test("returns LangGraphBackend when DOCKER_AGENT_BACKEND=langgraph", async () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "langgraph";
    const b = await createBackend();
    expect(b.name).toBe("langgraph");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test("falls back to current on unknown value", async () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "bogus";
    const b = await createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });
});

describe("AgentBackend interface typing", () => {
  test("AgentBackend has name and query method", () => {
    const b: AgentBackend = {
      name: "stub" as unknown as "current",
      query: async function* () {},
    };
    expect(b.name).toBe("stub");
  });
});

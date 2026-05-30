import type { ToolContext } from "src/Tool";
import type { ImageValidator } from "src/services/docker/imageValidator";
import { StateStore } from "src/state/StateStore";
import { pullImage } from "src/tools/pullImage";
import { describe, expect, test, vi } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

async function drainWithProgress<R>(
  gen: AsyncGenerator<{ type: "progress"; msg: string }, R>,
): Promise<{ progress: string[]; result: R }> {
  const progress: string[] = [];
  while (true) {
    const r = await gen.next();
    if (r.done) return { progress, result: r.value };
    progress.push(r.value.msg);
  }
}

function makeCtx(validator: ImageValidator, engine = new MockDockerEngine()): ToolContext {
  return {
    cwd: process.cwd(),
    stateStore: new StateStore(".docker-agent-test"),
    dockerEngine: engine as never,
    composeRunner: new MockComposeRunner() as never,
    abortSignal: new AbortController().signal,
    imageValidator: validator,
  };
}

describe("pull_image", () => {
  test("does not pull invalid registry images", async () => {
    const engine = new MockDockerEngine();
    const validator: ImageValidator = {
      validateImage: vi.fn(async () => ({
        image: "postgres:99-alpine",
        status: "invalid" as const,
        source: "registry" as const,
        error: "manifest not found",
        suggestion: "postgres:17-alpine",
      })),
      validateImages: vi.fn(),
    };

    const { result } = await drainWithProgress(
      pullImage.call({ image: "postgres:99-alpine" }, makeCtx(validator, engine)),
    );

    expect(result).toMatchObject({
      ok: false,
      status: "invalid",
      suggestion: "postgres:17-alpine",
    });
    expect(engine.pullImage).not.toHaveBeenCalled();
  });

  test("pulls images that are valid in a registry but not local", async () => {
    const engine = new MockDockerEngine();
    engine.pullImageLines = ["layer 1 complete", "done"];
    const validator: ImageValidator = {
      validateImage: vi.fn(async () => ({
        image: "nginx:1.27-alpine",
        status: "valid" as const,
        source: "registry" as const,
      })),
      validateImages: vi.fn(),
    };

    const { progress, result } = await drainWithProgress(
      pullImage.call({ image: "nginx:1.27-alpine" }, makeCtx(validator, engine)),
    );

    expect(result).toMatchObject({ ok: true, status: "valid", source: "pulled" });
    expect(engine.pullImage).toHaveBeenCalledWith("nginx:1.27-alpine", {
      signal: expect.any(AbortSignal),
    });
    expect(progress).toEqual([
      "Validating nginx:1.27-alpine...",
      "Pulling nginx:1.27-alpine...",
      "layer 1 complete",
      "done",
    ]);
  });
});

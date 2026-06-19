import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import type { ComposeRunner } from "src/services/docker/composeRunner";
import type { ImageValidator } from "src/services/docker/imageValidator";
import { StateStore } from "src/state/StateStore";
import { validateSpec } from "src/tools/validateSpec";
import { describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

async function drain<T, R>(gen: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await gen.next();
    if (r.done) return r.value;
  }
}

function makeCtx(tmpRoot: string, imageValidator?: ImageValidator): ToolContext {
  const store = new StateStore(path.join(tmpRoot, ".docker-agent"));
  return {
    cwd: tmpRoot,
    stateStore: store,
    dockerEngine: new MockDockerEngine() as never,
    composeRunner: new MockComposeRunner() as unknown as ComposeRunner,
    abortSignal: new AbortController().signal,
    ...(imageValidator ? { imageValidator } : {}),
  };
}

function invalidImageValidator(image: string): ImageValidator {
  return {
    validateImage: async () => ({
      image,
      status: "invalid",
      source: "registry",
      error: "manifest not found",
      suggestion: "postgres:17-alpine",
    }),
    validateImages: async () => [
      {
        image,
        status: "invalid",
        source: "registry",
        error: "manifest not found",
        suggestion: "postgres:17-alpine",
      },
    ],
  };
}

describe("validate_spec", () => {
  let tmpRoot: string;

  test("returns valid for a simple nginx spec", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "validate-"));
    const result = await drain(
      validateSpec.call({ services: { web: { image: "nginx:1.27-alpine" } } }, makeCtx(tmpRoot)),
    );
    expect(result).toEqual({ valid: true, issues: [], warnings: [] });
  });

  test("returns a structured observation for missing config content", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "validate-"));
    const result = await drain(
      validateSpec.call(
        {
          services: {
            web: {
              image: "nginx:1.27-alpine",
              volumes: ["./nginx.conf:/etc/nginx/nginx.conf"],
            },
          },
        },
        makeCtx(tmpRoot),
      ),
    );

    expect(result).toEqual({
      valid: false,
      issues: [
        {
          code: "missing_config_file",
          path: "services.web.volumes",
          message: "Missing content for bind-mounted config file './nginx.conf'.",
        },
      ],
      warnings: [],
    });
  });

  test("reports unsafe config path", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "validate-"));
    const result = await drain(
      validateSpec.call(
        {
          services: { web: { image: "nginx:1.27-alpine" } },
          configFiles: { "../escape.conf": "content" },
        },
        makeCtx(tmpRoot),
      ),
    );
    expect(result.valid).toBe(false);
    expect(result.issues[0]?.code).toBe("invalid_config_path");
  });

  test("reports invalid image", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "validate-"));
    const result = await drain(
      validateSpec.call(
        { services: { db: { image: "postgres:does-not-exist" } } },
        makeCtx(tmpRoot, invalidImageValidator("postgres:does-not-exist")),
      ),
    );
    expect(result.valid).toBe(false);
    expect(result.issues[0]?.code).toBe("invalid_image");
  });
});

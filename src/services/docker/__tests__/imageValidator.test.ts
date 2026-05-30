import type { EngineClient } from "src/services/docker/engineClient";
import { describe, expect, test, vi } from "vitest";
import { type RegistryClient, createImageValidator } from "../imageValidator";

function engineWithInspect(inspectImage: EngineClient["inspectImage"]): EngineClient {
  return {
    listContainers: vi.fn(),
    inspect: vi.fn(),
    inspectImage,
    listImages: vi.fn(),
    pullImage: vi.fn(),
  } as unknown as EngineClient;
}

describe("ImageValidator", () => {
  test("trusts an exact local image hit without querying a registry", async () => {
    const registry: RegistryClient = {
      checkImageExists: vi.fn(),
    };
    const engine = engineWithInspect(
      vi.fn(async () => ({
        Id: "sha256:local",
        RepoTags: ["postgres:16-alpine"],
        Size: 1,
        Architecture: "amd64",
        Os: "linux",
        Created: "2026-01-01T00:00:00Z",
      })),
    );

    const validator = createImageValidator(engine, registry);
    const result = await validator.validateImage("postgres:16-alpine");

    expect(result).toMatchObject({ status: "valid", source: "local" });
    expect(registry.checkImageExists).not.toHaveBeenCalled();
  });

  test("maps registry missing results to invalid validation failures", async () => {
    const registry: RegistryClient = {
      checkImageExists: vi.fn(async () => ({
        image: "postgres:99-alpine",
        status: "missing" as const,
        registry: "registry-1.docker.io",
        repository: "library/postgres",
        reference: "99-alpine",
        error: "manifest not found",
        suggestion: "postgres:17-alpine",
      })),
    };
    const engine = engineWithInspect(vi.fn(async () => null));

    const validator = createImageValidator(engine, registry);
    const result = await validator.validateImage("postgres:99-alpine");

    expect(result).toMatchObject({
      status: "invalid",
      source: "registry",
      suggestion: "postgres:17-alpine",
    });
  });

  test("caches registry validation results within the configured TTL", async () => {
    const registry: RegistryClient = {
      checkImageExists: vi.fn(async () => ({
        image: "nginx:1.27-alpine",
        status: "exists" as const,
        registry: "registry-1.docker.io",
        repository: "library/nginx",
        reference: "1.27-alpine",
      })),
    };
    const engine = engineWithInspect(vi.fn(async () => null));
    const validator = createImageValidator(engine, registry, {
      cacheTtlMs: 60_000,
      now: () => 100,
    });

    await validator.validateImage("nginx:1.27-alpine");
    await validator.validateImage("nginx:1.27-alpine");

    expect(registry.checkImageExists).toHaveBeenCalledOnce();
  });
});

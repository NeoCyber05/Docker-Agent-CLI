import { describe, expect, test } from "vitest";
import { parseImageReference } from "../imageReference";

describe("parseImageReference", () => {
  test("normalizes Docker Hub official images to library namespace", () => {
    expect(parseImageReference("postgres:16-alpine")).toMatchObject({
      original: "postgres:16-alpine",
      registry: "registry-1.docker.io",
      repository: "library/postgres",
      reference: "16-alpine",
      referenceType: "tag",
      normalized: "registry-1.docker.io/library/postgres:16-alpine",
    });
  });

  test("defaults Docker Hub images without tags to latest", () => {
    expect(parseImageReference("redis")).toMatchObject({
      repository: "library/redis",
      reference: "latest",
      referenceType: "tag",
      normalized: "registry-1.docker.io/library/redis:latest",
    });
  });

  test("keeps explicit registries, ports, and nested repositories", () => {
    expect(parseImageReference("localhost:5000/team/api:dev")).toMatchObject({
      registry: "localhost:5000",
      repository: "team/api",
      reference: "dev",
      referenceType: "tag",
      normalized: "localhost:5000/team/api:dev",
    });
  });

  test("normalizes docker.io registry aliases to the Registry API host", () => {
    expect(parseImageReference("docker.io/library/postgres:16")).toMatchObject({
      registry: "registry-1.docker.io",
      repository: "library/postgres",
      reference: "16",
      normalized: "registry-1.docker.io/library/postgres:16",
    });
  });

  test("supports digest references", () => {
    expect(parseImageReference("ghcr.io/acme/api@sha256:abc123")).toMatchObject({
      registry: "ghcr.io",
      repository: "acme/api",
      reference: "sha256:abc123",
      referenceType: "digest",
      normalized: "ghcr.io/acme/api@sha256:abc123",
    });
  });

  test("rejects blank image names", () => {
    expect(() => parseImageReference("   ")).toThrow("Docker image reference is required");
  });
});

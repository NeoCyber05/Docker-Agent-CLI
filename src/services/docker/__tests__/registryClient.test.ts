import { describe, expect, test, vi } from "vitest";
import { createRegistryClient } from "../registryClient";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("RegistryClient", () => {
  test("follows Docker Registry bearer-token challenge before checking a manifest", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(
        new Response(null, {
          status: 401,
          headers: {
            "www-authenticate":
              'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/postgres:pull"',
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ token: "registry-token" }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));

    const client = createRegistryClient({ fetch, timeoutMs: 0 });
    const result = await client.checkImageExists("postgres:16-alpine");

    expect(result).toMatchObject({
      status: "exists",
      registry: "registry-1.docker.io",
      repository: "library/postgres",
      reference: "16-alpine",
    });
    expect(fetch.mock.calls[2]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer registry-token",
    });
  });

  test("returns missing with a nearby tag suggestion when the manifest is 404", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(
        new Response(null, {
          status: 401,
          headers: {
            "www-authenticate":
              'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/postgres:pull"',
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ token: "registry-token" }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(jsonResponse({ tags: ["15-alpine", "16-alpine", "17-alpine"] }));

    const client = createRegistryClient({ fetch, timeoutMs: 0 });
    const result = await client.checkImageExists("postgres:18-alpine");

    expect(result).toMatchObject({
      status: "missing",
      suggestion: "postgres:17-alpine",
    });
  });

  test("treats rate limits as unknown instead of invalid", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(
      new Response(null, {
        status: 429,
        statusText: "Too Many Requests",
      }),
    );

    const client = createRegistryClient({ fetch, timeoutMs: 0 });
    const result = await client.checkImageExists("nginx:1.27-alpine");

    expect(result).toMatchObject({
      status: "unknown",
      error: expect.stringContaining("429"),
    });
  });
});

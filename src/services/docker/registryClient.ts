import { parseImageReference } from "./imageReference";

export type RegistryCheckStatus = "exists" | "missing" | "unknown";

export interface RegistryCheckResult {
  image: string;
  status: RegistryCheckStatus;
  registry: string;
  repository: string;
  reference: string;
  error?: string;
  suggestion?: string;
}

export interface RegistryClient {
  checkImageExists(image: string, opts?: { signal?: AbortSignal }): Promise<RegistryCheckResult>;
}

export interface RegistryClientOptions {
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
}

const MANIFEST_ACCEPT = [
  "application/vnd.oci.image.index.v1+json",
  "application/vnd.oci.image.manifest.v1+json",
  "application/vnd.docker.distribution.manifest.list.v2+json",
  "application/vnd.docker.distribution.manifest.v2+json",
  "application/vnd.docker.distribution.manifest.v1+json",
].join(", ");

interface BearerChallenge {
  realm: string;
  service?: string;
  scope?: string;
}

function resultBase(image: string) {
  const ref = parseImageReference(image);
  return {
    image: ref.original,
    registry: ref.registry,
    repository: ref.repository,
    reference: ref.reference,
  };
}

function registryBaseUrl(registry: string): string {
  return `https://${registry}`;
}

function parseBearerChallenge(value: string | null): BearerChallenge | null {
  if (!value?.startsWith("Bearer ")) return null;
  const params = value.slice("Bearer ".length);
  const parsed: Record<string, string> = {};
  for (const match of params.matchAll(/([a-zA-Z]+)="([^"]*)"/g)) {
    parsed[match[1] ?? ""] = match[2] ?? "";
  }
  if (!parsed.realm) return null;
  return {
    realm: parsed.realm,
    ...(parsed.service ? { service: parsed.service } : {}),
    ...(parsed.scope ? { scope: parsed.scope } : {}),
  };
}

async function requestBearerToken(
  challenge: BearerChallenge,
  fetchImpl: typeof globalThis.fetch,
  signal?: AbortSignal,
): Promise<string | null> {
  const url = new URL(challenge.realm);
  if (challenge.service) url.searchParams.set("service", challenge.service);
  if (challenge.scope) url.searchParams.set("scope", challenge.scope);

  const response = await fetchImpl(url, signal ? { signal } : {});
  if (!response.ok) return null;
  const body = (await response.json()) as { token?: string; access_token?: string };
  return body.token ?? body.access_token ?? null;
}

function createAbortSignal(
  timeoutMs: number,
  signal?: AbortSignal,
): {
  signal?: AbortSignal;
  cleanup: () => void;
} {
  if (timeoutMs <= 0) return signal ? { signal, cleanup: () => {} } : { cleanup: () => {} };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    },
  };
}

function manifestUrl(image: string): string {
  const ref = parseImageReference(image);
  return `${registryBaseUrl(ref.registry)}/v2/${ref.repository}/manifests/${encodeURIComponent(
    ref.reference,
  )}`;
}

function tagsUrl(image: string): string {
  const ref = parseImageReference(image);
  return `${registryBaseUrl(ref.registry)}/v2/${ref.repository}/tags/list?n=100`;
}

function formatStatus(response: Response): string {
  return `${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
}

function suggestTag(image: string, tags: string[]): string | undefined {
  const ref = parseImageReference(image);
  if (ref.referenceType !== "tag") return undefined;
  const match = /^(\d+)(.*)$/.exec(ref.reference);
  if (!match)
    return tags.includes("latest") ? ref.original.replace(/:[^/:]+$/, ":latest") : undefined;
  const requestedMajor = Number(match[1]);
  const suffix = match[2] ?? "";
  const candidates = tags
    .map((tag) => {
      const candidate = /^(\d+)(.*)$/.exec(tag);
      if (!candidate || candidate[2] !== suffix) return null;
      return { major: Number(candidate[1]), tag };
    })
    .filter((candidate): candidate is { major: number; tag: string } => candidate !== null)
    .filter((candidate) => candidate.major < requestedMajor)
    .sort((a, b) => b.major - a.major);
  const best = candidates[0]?.tag;
  if (!best) return undefined;
  return `${ref.original.replace(/(:[^/:@]+)?(@.+)?$/, "")}:${best}`;
}

async function fetchTags(
  image: string,
  fetchImpl: typeof globalThis.fetch,
  token: string | null,
  signal?: AbortSignal,
): Promise<string[]> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetchImpl(tagsUrl(image), {
    headers,
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) return [];
  const body = (await response.json()) as { tags?: unknown };
  return Array.isArray(body.tags)
    ? body.tags.filter((tag): tag is string => typeof tag === "string")
    : [];
}

export function createRegistryClient(options: RegistryClientOptions = {}): RegistryClient {
  const fetchImpl = options.fetch ?? globalThis.fetch;
  const timeoutMs = options.timeoutMs ?? 10_000;

  return {
    async checkImageExists(image, opts = {}) {
      const base = resultBase(image);
      const timeout = createAbortSignal(timeoutMs, opts.signal);
      try {
        let token: string | null = null;
        let response = await fetchImpl(manifestUrl(image), {
          method: "HEAD",
          headers: { Accept: MANIFEST_ACCEPT },
          ...(timeout.signal ? { signal: timeout.signal } : {}),
        });

        if (response.status === 401) {
          const challenge = parseBearerChallenge(response.headers.get("www-authenticate"));
          if (!challenge) {
            return { ...base, status: "unknown", error: "registry requires unsupported auth" };
          }
          token = await requestBearerToken(challenge, fetchImpl, timeout.signal);
          if (!token) return { ...base, status: "unknown", error: "registry token request failed" };
          response = await fetchImpl(manifestUrl(image), {
            method: "HEAD",
            headers: { Accept: MANIFEST_ACCEPT, Authorization: `Bearer ${token}` },
            ...(timeout.signal ? { signal: timeout.signal } : {}),
          });
        }

        if (response.status === 405) {
          response = await fetchImpl(manifestUrl(image), {
            method: "GET",
            headers: {
              Accept: MANIFEST_ACCEPT,
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            ...(timeout.signal ? { signal: timeout.signal } : {}),
          });
        }

        if (response.ok) return { ...base, status: "exists" };
        if (response.status === 404) {
          const tags = await fetchTags(image, fetchImpl, token, timeout.signal);
          const suggestion = suggestTag(image, tags);
          return {
            ...base,
            status: "missing",
            error: "manifest not found",
            ...(suggestion ? { suggestion } : {}),
          };
        }
        if (response.status === 401 || response.status === 403) {
          return { ...base, status: "unknown", error: "registry requires authentication" };
        }
        return { ...base, status: "unknown", error: `registry returned ${formatStatus(response)}` };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return { ...base, status: "unknown", error: message };
      } finally {
        timeout.cleanup();
      }
    },
  };
}

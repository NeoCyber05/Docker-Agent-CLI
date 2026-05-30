import type { EngineClient } from "./engineClient";
import { parseImageReference } from "./imageReference";
import {
  type RegistryCheckResult,
  type RegistryClient,
  createRegistryClient,
} from "./registryClient";

export type { RegistryClient };

export type ImageValidationStatus = "valid" | "invalid" | "unknown";
export type ImageValidationSource = "local" | "registry" | "unavailable";

export interface ImageValidationResult {
  image: string;
  status: ImageValidationStatus;
  source: ImageValidationSource;
  error?: string;
  suggestion?: string;
}

export interface ImageValidator {
  validateImage(image: string, opts?: { signal?: AbortSignal }): Promise<ImageValidationResult>;
  validateImages(
    images: string[],
    opts?: { signal?: AbortSignal },
  ): Promise<ImageValidationResult[]>;
}

export interface ImageValidatorOptions {
  cacheTtlMs?: number;
  now?: () => number;
}

interface CacheEntry {
  expiresAt: number;
  result: ImageValidationResult;
}

function registryResultToValidation(result: RegistryCheckResult): ImageValidationResult {
  if (result.status === "exists") {
    return { image: result.image, status: "valid", source: "registry" };
  }
  if (result.status === "missing") {
    return {
      image: result.image,
      status: "invalid",
      source: "registry",
      ...(result.error ? { error: result.error } : {}),
      ...(result.suggestion ? { suggestion: result.suggestion } : {}),
    };
  }
  return {
    image: result.image,
    status: "unknown",
    source: "unavailable",
    ...(result.error ? { error: result.error } : {}),
  };
}

function localValidation(image: string): ImageValidationResult {
  return { image, status: "valid", source: "local" };
}

export function createImageValidator(
  engineClient: EngineClient,
  registryClient: RegistryClient = createRegistryClient(),
  options: ImageValidatorOptions = {},
): ImageValidator {
  const cacheTtlMs = options.cacheTtlMs ?? 60 * 60 * 1000;
  const now = options.now ?? Date.now;
  const cache = new Map<string, CacheEntry>();

  async function validateImage(
    image: string,
    opts: { signal?: AbortSignal } = {},
  ): Promise<ImageValidationResult> {
    try {
      parseImageReference(image);
    } catch (error) {
      return {
        image,
        status: "invalid",
        source: "unavailable",
        error: error instanceof Error ? error.message : String(error),
      };
    }

    const local = engineClient.inspectImage
      ? await engineClient.inspectImage(image).catch(() => null)
      : null;
    if (local) return localValidation(image);

    const cached = cache.get(image);
    if (cached && cached.expiresAt > now()) return cached.result;

    const result = registryResultToValidation(
      await registryClient.checkImageExists(image, opts.signal ? { signal: opts.signal } : {}),
    );
    cache.set(image, { result, expiresAt: now() + cacheTtlMs });
    return result;
  }

  return {
    validateImage,
    async validateImages(images, opts = {}) {
      const uniqueImages = [...new Set(images)];
      const byImage = new Map<string, ImageValidationResult>();
      const validations = await Promise.all(
        uniqueImages.map(async (image) => [image, await validateImage(image, opts)] as const),
      );
      for (const [image, result] of validations) byImage.set(image, result);
      return images.map((image) => byImage.get(image) ?? localValidation(image));
    },
  };
}

export function formatImageValidationError(
  results: ImageValidationResult[],
  opts: { blockUnknown?: boolean } = {},
): string | null {
  const failures = results.filter(
    (result) => result.status === "invalid" || (opts.blockUnknown && result.status === "unknown"),
  );
  if (failures.length === 0) return null;
  const lines = failures.map((result) => {
    const reason = result.error ?? "could not verify image";
    const suggestion = result.suggestion ? ` Did you mean '${result.suggestion}'?` : "";
    return `- ${result.image}: ${reason}.${suggestion}`;
  });
  return `Invalid Docker images detected:\n${lines.join("\n")}`;
}

export function imageValidationWarnings(results: ImageValidationResult[]): string[] {
  return results
    .filter((result) => result.status === "unknown")
    .map(
      (result) =>
        `warning: could not verify Docker image '${result.image}'${
          result.error ? ` (${result.error})` : ""
        }`,
    );
}

export type ImageReferenceType = "tag" | "digest";

export interface ImageReference {
  original: string;
  registry: string;
  repository: string;
  reference: string;
  referenceType: ImageReferenceType;
  normalized: string;
}

const DEFAULT_DOCKER_HUB_REGISTRY = "registry-1.docker.io";
const DEFAULT_TAG = "latest";

function isExplicitRegistry(firstPart: string): boolean {
  return firstPart === "localhost" || firstPart.includes(".") || firstPart.includes(":");
}

function normalizeRepository(registry: string, repository: string): string {
  if (registry === DEFAULT_DOCKER_HUB_REGISTRY && !repository.includes("/")) {
    return `library/${repository}`;
  }
  return repository;
}

function normalizeRegistry(registry: string): string {
  if (registry === "docker.io" || registry === "index.docker.io") {
    return DEFAULT_DOCKER_HUB_REGISTRY;
  }
  return registry;
}

export function parseImageReference(input: string): ImageReference {
  const original = input.trim();
  if (!original) throw new Error("Docker image reference is required");

  const [namePart, digestPart] = original.split("@", 2);
  if (!namePart) throw new Error(`Invalid Docker image reference '${input}'`);

  const slashIndex = namePart.indexOf("/");
  const firstPart = slashIndex >= 0 ? namePart.slice(0, slashIndex) : namePart;
  const hasExplicitRegistry = slashIndex >= 0 && isExplicitRegistry(firstPart);
  const registry = hasExplicitRegistry ? normalizeRegistry(firstPart) : DEFAULT_DOCKER_HUB_REGISTRY;
  const repositoryAndTag = hasExplicitRegistry ? namePart.slice(slashIndex + 1) : namePart;
  if (!repositoryAndTag) throw new Error(`Invalid Docker image reference '${input}'`);

  const lastSlash = repositoryAndTag.lastIndexOf("/");
  const lastColon = repositoryAndTag.lastIndexOf(":");
  const hasTag = lastColon > lastSlash;
  const repositoryName = hasTag ? repositoryAndTag.slice(0, lastColon) : repositoryAndTag;
  const tag = hasTag ? repositoryAndTag.slice(lastColon + 1) : DEFAULT_TAG;
  if (!repositoryName || (!digestPart && !tag)) {
    throw new Error(`Invalid Docker image reference '${input}'`);
  }

  const repository = normalizeRepository(registry, repositoryName);
  if (digestPart) {
    return {
      original,
      registry,
      repository,
      reference: digestPart,
      referenceType: "digest",
      normalized: `${registry}/${repository}@${digestPart}`,
    };
  }

  return {
    original,
    registry,
    repository,
    reference: tag,
    referenceType: "tag",
    normalized: `${registry}/${repository}:${tag}`,
  };
}

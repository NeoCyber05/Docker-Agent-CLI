# Implementation Plan: Docker Image Validation System

## Problem Statement

When using local LLMs (Ollama with Llama 3, Qwen, Mistral), the agent frequently hallucinates non-existent Docker image tags (e.g., `postgres:18-alpine` when version 18 doesn't exist). This causes Docker Compose deployment failures and disrupts the system. Currently, `src/tools/pullImage.ts` is a placeholder that always returns `{ ok: true }` without any validation.

## Goals

1. Implement real Docker image validation before deployment
2. Verify image:tag existence on Docker registries (Docker Hub, etc.)
3. Provide clear error messages when images don't exist
4. Optionally pre-pull images to ensure local availability
5. Integrate validation into the agent workflow to catch hallucinations early

## Architecture Overview

### Current State
- `pullImage.ts`: Placeholder tool, always returns success
- `EngineClient`: Limited interface (listContainers, inspect)
- No image validation in stack planning or application flow
- Uses `dockerode` library for Docker API access

### Proposed Changes
```
┌─────────────────────────────────────────────────────────┐
│ Agent generates stack with image references             │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ planStack: Extract all image references                 │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ validateImages: Check each image exists                 │
│  1. Try local image inspection (fast)                   │
│  2. If not local, query Docker Registry API             │
│  3. Return validation results                           │
└────────────────┬────────────────────────────────────────┘
                 │
                 ├─ Valid ──────────────────────┐
                 │                               │
                 ├─ Invalid ─> Return error      │
                 │             to agent          │
                 │                               │
                 └─ Unknown ─> Warn but allow   │
                               (private registry)│
                                                 ▼
                 ┌───────────────────────────────────────┐
                 │ applyStack: Deploy with confidence    │
                 └───────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Extend Docker Engine Client

**File:** `src/services/docker/engineClient.ts`

**Changes:**
1. Add image-related methods to `EngineClient` interface:
   ```typescript
   interface EngineClient {
     // ... existing methods
     inspectImage(nameOrId: string): Promise<ImageInspect | null>;
     pullImage(image: string): AsyncGenerator<string, void>;
     listImages(opts?: { filters?: Record<string, string[]> }): Promise<ImageSummary[]>;
   }
   ```

2. Define new types:
   ```typescript
   interface ImageSummary {
     Id: string;
     RepoTags: string[];
     Size: number;
     Created: number;
   }
   
   interface ImageInspect {
     Id: string;
     RepoTags: string[];
     Size: number;
     Architecture: string;
     Os: string;
     Created: string;
   }
   ```

3. Implement methods in `createEngineClient()`:
   - `inspectImage`: Use `docker.getImage(name).inspect()`, return null if not found
   - `pullImage`: Use `docker.pull()` with streaming progress
   - `listImages`: Use `docker.listImages()`

**Why:** Provides low-level Docker API access needed for image operations.

### Phase 2: Docker Registry API Client

**New File:** `src/services/docker/registryClient.ts`

**Purpose:** Query Docker Hub and other registries to verify image:tag existence without pulling.

**Implementation:**
1. Parse image reference into components:
   ```typescript
   interface ImageRef {
     registry: string;      // default: registry-1.docker.io
     namespace: string;     // default: library
     repository: string;
     tag: string;          // default: latest
   }
   
   function parseImageRef(image: string): ImageRef
   ```

2. Implement registry API queries:
   ```typescript
   interface RegistryClient {
     checkImageExists(image: string): Promise<ImageCheckResult>;
   }
   
   interface ImageCheckResult {
     exists: boolean;
     registry: string;
     error?: string;
     availableTags?: string[];  // for suggestions
   }
   ```

3. Support Docker Hub API v2:
   - Endpoint: `https://registry-1.docker.io/v2/{namespace}/{repo}/manifests/{tag}`
   - Handle authentication for private images (optional)
   - Handle rate limiting (429 responses)

4. Fallback strategy:
   - If registry API fails, mark as "unknown" (don't block private registries)
   - Log warnings for debugging

**Why:** Validates images without downloading them, saving time and bandwidth.

### Phase 3: Image Validation Service

**New File:** `src/services/docker/imageValidator.ts`

**Purpose:** High-level validation logic combining local and registry checks.

**Implementation:**
```typescript
interface ValidationResult {
  image: string;
  status: 'valid' | 'invalid' | 'unknown';
  source: 'local' | 'registry' | 'unavailable';
  error?: string;
  suggestion?: string;
}

interface ImageValidator {
  validateImage(image: string): Promise<ValidationResult>;
  validateImages(images: string[]): Promise<ValidationResult[]>;
}

function createImageValidator(
  engineClient: EngineClient,
  registryClient: RegistryClient
): ImageValidator
```

**Validation Flow:**
1. Check if image exists locally (`engineClient.inspectImage`)
   - If found → return `{ status: 'valid', source: 'local' }`
2. If not local, query registry API (`registryClient.checkImageExists`)
   - If exists → return `{ status: 'valid', source: 'registry' }`
   - If 404 → return `{ status: 'invalid', error: '...', suggestion: '...' }`
   - If error → return `{ status: 'unknown', source: 'unavailable' }`

**Error Messages:**
- Invalid: `"Image 'postgres:18-alpine' not found. Did you mean 'postgres:17-alpine'?"`
- Unknown: `"Could not verify 'myregistry.com/app:v1' (private registry or network error)"`

**Why:** Provides a clean, testable interface for image validation.

### Phase 4: Update pullImage Tool

**File:** `src/tools/pullImage.ts`

**Changes:**
1. Update `PullImageResult`:
   ```typescript
   interface PullImageResult {
     ok: boolean;
     status: 'valid' | 'invalid' | 'unknown';
     source?: 'local' | 'registry' | 'pulled';
     error?: string;
     suggestion?: string;
   }
   ```

2. Implement real validation logic:
   ```typescript
   call: async function* (input, ctx) {
     const validator = createImageValidator(
       ctx.dockerEngine,
       createRegistryClient()
     );
     
     yield { type: "progress", msg: `Validating ${input.image}...` };
     
     const result = await validator.validateImage(input.image);
     
     if (result.status === 'invalid') {
       return {
         ok: false,
         status: 'invalid',
         error: result.error,
         suggestion: result.suggestion
       };
     }
     
     if (result.status === 'valid' && result.source === 'registry') {
       // Optionally pull the image
       yield { type: "progress", msg: `Pulling ${input.image}...` };
       for await (const line of ctx.dockerEngine.pullImage(input.image)) {
         yield { type: "progress", msg: line };
       }
       return { ok: true, status: 'valid', source: 'pulled' };
     }
     
     return { ok: true, status: result.status, source: result.source };
   }
   ```

3. Update description to reflect real functionality

**Why:** Transforms placeholder into functional validation tool.

### Phase 5: Integrate into Stack Planning

**File:** `src/tools/planStack.ts`

**Changes:**
1. After generating stack definition, extract all image references:
   ```typescript
   function extractImages(stack: StackDefinition): string[] {
     return Object.values(stack.services).map(svc => svc.image);
   }
   ```

2. Validate all images before returning plan:
   ```typescript
   const images = extractImages(stackDef);
   const validator = createImageValidator(ctx.dockerEngine, createRegistryClient());
   const validations = await validator.validateImages(images);
   
   const invalid = validations.filter(v => v.status === 'invalid');
   if (invalid.length > 0) {
     const errors = invalid.map(v => 
       `- ${v.image}: ${v.error}${v.suggestion ? ` (${v.suggestion})` : ''}`
     ).join('\n');
     
     throw new Error(
       `Invalid Docker images detected:\n${errors}\n\n` +
       `Please verify the image names and tags are correct.`
     );
   }
   ```

3. Include validation results in plan output for user visibility

**Why:** Catches hallucinated images early in the workflow, before deployment.

### Phase 6: Testing

**Test Files:**
1. `src/services/docker/__tests__/registryClient.test.ts`
   - Mock HTTP responses from Docker Hub API
   - Test parsing of various image formats
   - Test error handling (404, 429, network errors)

2. `src/services/docker/__tests__/imageValidator.test.ts`
   - Mock `EngineClient` and `RegistryClient`
   - Test validation flow (local → registry → unknown)
   - Test batch validation

3. `src/tools/__tests__/pullImage.test.ts`
   - Update existing tests to cover real validation
   - Test success, failure, and unknown cases
   - Test progress reporting

4. Integration test in `src/tools/__tests__/planStack.test.ts`
   - Test that invalid images are rejected during planning
   - Test error messages and suggestions

**Why:** Ensures reliability and prevents regressions.

## Configuration & Extensibility

### Environment Variables
```bash
# Optional: Custom registry URL
DOCKER_REGISTRY_URL=https://registry-1.docker.io

# Optional: Registry authentication
DOCKER_REGISTRY_USERNAME=
DOCKER_REGISTRY_PASSWORD=

# Optional: Disable registry validation (for air-gapped environments)
DISABLE_REGISTRY_VALIDATION=false

# Optional: Pull images during validation
AUTO_PULL_IMAGES=false
```

### Future Enhancements
1. Cache validation results (TTL: 1 hour) to avoid repeated API calls
2. Support multiple registries (Docker Hub, GitHub Container Registry, etc.)
3. Suggest alternative tags when exact match not found (fuzzy matching)
4. Add `--skip-validation` flag for advanced users
5. Parallel validation for multiple images

## Risk Mitigation

### Private Registries
- Don't block deployment if registry is unreachable
- Return `status: 'unknown'` and log warning
- Allow users to configure trusted registries

### Rate Limiting
- Docker Hub: 100 pulls/6 hours for anonymous, 200/6h for authenticated
- Implement exponential backoff
- Cache results to minimize API calls

### Network Failures
- Timeout after 10 seconds per image
- Graceful degradation: warn but don't block

### False Positives
- If local Docker daemon has the image, trust it (don't require registry check)
- Provide override mechanism for edge cases

## Success Criteria

1. ✅ Agent can no longer deploy stacks with non-existent images
2. ✅ Clear error messages guide users to correct image names
3. ✅ Validation completes in <5 seconds for typical stacks (3-5 services)
4. ✅ Private registries continue to work (no false negatives)
5. ✅ All tests pass with >90% coverage for new code

## Implementation Order

1. **Phase 1** (EngineClient) - Foundation for all image operations
2. **Phase 2** (RegistryClient) - Core validation capability
3. **Phase 3** (ImageValidator) - Business logic layer
4. **Phase 4** (pullImage tool) - User-facing tool update
5. **Phase 5** (planStack integration) - Automatic validation in workflow
6. **Phase 6** (Testing) - Continuous throughout, finalize at end

## Estimated Effort

- Phase 1: 2-3 hours (Docker API integration)
- Phase 2: 3-4 hours (Registry API client + parsing)
- Phase 3: 2 hours (Validation service)
- Phase 4: 1 hour (Tool update)
- Phase 5: 2 hours (Integration)
- Phase 6: 3-4 hours (Comprehensive testing)

**Total: 13-16 hours**

## Dependencies

- `dockerode` (already installed) - Docker Engine API
- No new dependencies required for Docker Hub API (use native `fetch`)
- Consider adding `node-cache` for future caching enhancement (optional)

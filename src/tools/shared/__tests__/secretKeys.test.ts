import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { StateStore } from "src/state/StateStore";
import { collectSecretKeys } from "src/tools/shared/secretKeys";
import { beforeEach, describe, expect, test } from "vitest";

describe("collectSecretKeys", () => {
  let tmpRoot: string;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "seckeys-"));
  });

  test("merges addedKeys, secret-looking environment keys, and secret env_file keys", () => {
    const store = new StateStore(path.join(tmpRoot, ".docker-agent"));

    // A generated secrets file referenced by the service's env_file.
    const secretsDir = path.join(tmpRoot, ".docker-agent", "secrets");
    fs.mkdirSync(secretsDir, { recursive: true });
    fs.writeFileSync(
      path.join(secretsDir, "web-web.env"),
      "JWT_TOKEN=abc\nDB_PASSWORD=secret\nDEBUG=true\n",
    );

    store.write("web", {
      "x-docker-agent": {
        name: "web",
        createdAt: "x",
        lastApplied: null,
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {
          web: { generated: true, path: "x", addedKeys: ["API_KEY"] },
        },
      },
      services: {
        web: {
          image: "nginx",
          environment: { DB_PASSWORD: "secret", PORT: "8080" },
          env_file: ["./.docker-agent/secrets/web-web.env"],
        },
      },
    });

    const result = collectSecretKeys("web", { cwd: tmpRoot, stateStore: store });

    expect(result).toBeInstanceOf(Set);
    // API_KEY (addedKeys), DB_PASSWORD (env shouldRedact), JWT_TOKEN (env_file shouldRedact).
    expect([...result].sort()).toEqual(["API_KEY", "DB_PASSWORD", "JWT_TOKEN"]);
    // PORT (not secret) and DEBUG (env_file, not secret) are excluded.
    expect(result.has("PORT")).toBe(false);
    expect(result.has("DEBUG")).toBe(false);
  });

  test("returns empty set when stack is unknown", () => {
    const store = new StateStore(path.join(tmpRoot, ".docker-agent"));
    const result = collectSecretKeys("ghost", { cwd: tmpRoot, stateStore: store });
    expect(result.size).toBe(0);
  });
});

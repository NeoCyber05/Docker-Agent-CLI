import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  restoreConfigFiles,
  snapshotConfigFiles,
  writeConfigFiles,
} from "src/tools/shared/configFiles";
import { describe, expect, test } from "vitest";

// This mirrors the applyWithRollback sequence: snapshot -> write -> (on failure) restore.
describe("apply config-file lifecycle (integration of helpers)", () => {
  test("a failed apply leaves no newly created config file behind", () => {
    const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "apply-cfg-"));
    const staged = [{ path: "nginx.conf", content: "events {}", bytes: 9 }];

    const snaps = snapshotConfigFiles(cwd, staged);
    writeConfigFiles(cwd, staged);
    expect(fs.existsSync(path.join(cwd, "nginx.conf"))).toBe(true);

    // Simulate apply failure -> rollback restores snapshots.
    restoreConfigFiles(snaps);
    expect(fs.existsSync(path.join(cwd, "nginx.conf"))).toBe(false);
  });
});

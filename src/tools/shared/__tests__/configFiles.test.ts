import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  detectMissingConfigFiles,
  findInvalidFileBinds,
  isFileLikeBind,
  parseBindMount,
  resolveSafe,
  restoreConfigFiles,
  snapshotConfigFiles,
  stageConfigFiles,
  writeConfigFiles,
} from "src/tools/shared/configFiles";
import { beforeEach, describe, expect, test } from "vitest";

describe("parseBindMount", () => {
  test("parses a relative bind mount", () => {
    expect(parseBindMount("./nginx.conf:/etc/nginx/nginx.conf")).toEqual({
      source: "./nginx.conf",
      target: "/etc/nginx/nginx.conf",
    });
  });
  test("captures a mode suffix", () => {
    expect(parseBindMount("./nginx.conf:/etc/nginx/nginx.conf:ro")).toEqual({
      source: "./nginx.conf",
      target: "/etc/nginx/nginx.conf",
      mode: "ro",
    });
  });
  test("returns null for a named volume", () => {
    expect(parseBindMount("pgdata:/var/lib/postgresql/data")).toBeNull();
  });
});

describe("isFileLikeBind", () => {
  test("true when the host path has an extension", () => {
    expect(isFileLikeBind("./nginx.conf")).toBe(true);
    expect(isFileLikeBind("./conf/app.yaml")).toBe(true);
  });
  test("false for a directory mount", () => {
    expect(isFileLikeBind("./data")).toBe(false);
    expect(isFileLikeBind("./html")).toBe(false);
  });
});

describe("resolveSafe", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-safe-"));
  });
  test("accepts an in-cwd relative path", () => {
    const r = resolveSafe(cwd, "./nginx.conf");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.abs).toBe(path.join(cwd, "nginx.conf"));
  });
  test("rejects path traversal", () => {
    expect(resolveSafe(cwd, "../escape.conf").ok).toBe(false);
  });
  test("rejects an absolute path", () => {
    expect(resolveSafe(cwd, "/etc/passwd").ok).toBe(false);
  });
  test("rejects the reserved .docker-agent subtree", () => {
    expect(resolveSafe(cwd, "./.docker-agent/x.env").ok).toBe(false);
  });
});

describe("detectMissingConfigFiles", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-detect-"));
  });
  test("reports a file bind with no content and no host file", () => {
    const services = { nginx: { image: "nginx", volumes: ["./nginx.conf:/etc/nginx/nginx.conf"] } };
    expect(detectMissingConfigFiles(services, new Set(), cwd)).toEqual([
      { service: "nginx", path: "./nginx.conf" },
    ]);
  });
  test("does not report when content is provided", () => {
    const services = { nginx: { image: "nginx", volumes: ["./nginx.conf:/etc/nginx/nginx.conf"] } };
    expect(detectMissingConfigFiles(services, new Set(["nginx.conf"]), cwd)).toEqual([]);
  });
  test("does not report a directory mount", () => {
    const services = { web: { image: "nginx", volumes: ["./html:/usr/share/nginx/html"] } };
    expect(detectMissingConfigFiles(services, new Set(), cwd)).toEqual([]);
  });
  test("does not report when the host file already exists", () => {
    fs.writeFileSync(path.join(cwd, "nginx.conf"), "x");
    const services = { nginx: { image: "nginx", volumes: ["./nginx.conf:/etc/nginx/nginx.conf"] } };
    expect(detectMissingConfigFiles(services, new Set(), cwd)).toEqual([]);
  });
});

describe("findInvalidFileBinds", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-invalid-"));
  });
  const services = {
    nginx: { image: "nginx", volumes: ["./nginx.conf:/etc/nginx/nginx.conf:ro"] },
  };

  test("flags a missing file-bind source (Docker would auto-create a dir)", () => {
    expect(findInvalidFileBinds(services, cwd)).toEqual([
      { service: "nginx", path: "./nginx.conf", reason: "missing" },
    ]);
  });
  test("flags a directory squatting at the source", () => {
    fs.mkdirSync(path.join(cwd, "nginx.conf"));
    expect(findInvalidFileBinds(services, cwd)).toEqual([
      { service: "nginx", path: "./nginx.conf", reason: "directory" },
    ]);
  });
  test("accepts a real file at the source", () => {
    fs.writeFileSync(path.join(cwd, "nginx.conf"), "events {}");
    expect(findInvalidFileBinds(services, cwd)).toEqual([]);
  });
  test("ignores directory mounts and named volumes", () => {
    const svc = {
      web: { image: "nginx", volumes: ["./html:/usr/share/nginx/html", "pgdata:/var/lib/x"] },
    };
    expect(findInvalidFileBinds(svc, cwd)).toEqual([]);
  });
});

describe("writeConfigFiles dir recovery", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-dirheal-"));
  });

  test("replaces a Docker-auto-created directory with the real file", () => {
    // simulate Docker leaving an empty directory at the bind source
    fs.mkdirSync(path.join(cwd, "nginx.conf"));
    writeConfigFiles(cwd, [{ path: "nginx.conf", content: "events {}", bytes: 9 }]);
    const stat = fs.statSync(path.join(cwd, "nginx.conf"));
    expect(stat.isFile()).toBe(true);
    expect(fs.readFileSync(path.join(cwd, "nginx.conf"), "utf8")).toBe("events {}");
  });
});

describe("stageConfigFiles", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-stage-"));
  });
  const nginx = { nginx: { image: "nginx", volumes: ["./nginx.conf:/etc/nginx/nginx.conf"] } };

  test("stages provided content for a matching file bind", () => {
    const r = stageConfigFiles(cwd, nginx, { "./nginx.conf": "events {}" });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.staged).toEqual([{ path: "nginx.conf", content: "events {}", bytes: 9 }]);
  });
  test("rejects an unsafe path", () => {
    const r = stageConfigFiles(cwd, nginx, { "../evil.conf": "x" });
    expect(r.ok).toBe(false);
  });
  test("rejects content that matches no file bind (dangling)", () => {
    const r = stageConfigFiles(cwd, nginx, { "./unused.conf": "x" });
    expect(r.ok).toBe(false);
  });
  test("rejects a file over 64 KiB", () => {
    const r = stageConfigFiles(cwd, nginx, { "./nginx.conf": "a".repeat(64 * 1024 + 1) });
    expect(r.ok).toBe(false);
  });
});

describe("snapshot/write/restore", () => {
  let cwd: string;
  beforeEach(() => {
    cwd = fs.mkdtempSync(path.join(os.tmpdir(), "cfg-rw-"));
  });

  test("write then restore removes a newly created file", () => {
    const staged = [{ path: "nginx.conf", content: "events {}", bytes: 9 }];
    const snaps = snapshotConfigFiles(cwd, staged);
    writeConfigFiles(cwd, staged);
    expect(fs.existsSync(path.join(cwd, "nginx.conf"))).toBe(true);
    restoreConfigFiles(snaps);
    expect(fs.existsSync(path.join(cwd, "nginx.conf"))).toBe(false);
  });

  test("write then restore brings back overwritten content", () => {
    fs.writeFileSync(path.join(cwd, "nginx.conf"), "ORIGINAL");
    const staged = [{ path: "nginx.conf", content: "NEW", bytes: 3 }];
    const snaps = snapshotConfigFiles(cwd, staged);
    writeConfigFiles(cwd, staged);
    expect(fs.readFileSync(path.join(cwd, "nginx.conf"), "utf8")).toBe("NEW");
    restoreConfigFiles(snaps);
    expect(fs.readFileSync(path.join(cwd, "nginx.conf"), "utf8")).toBe("ORIGINAL");
  });
});

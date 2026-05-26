import { vi } from "vitest";

export interface WrittenFile {
  path: string;
  content: string;
  mode?: number;
}

export class FsMock {
  files = new Map<string, string>();
  writtenFiles: WrittenFile[] = [];

  read(path: string): string {
    const v = this.files.get(path);
    if (v === undefined) throw new Error(`fsMock: no file ${path}`);
    return v;
  }

  write = vi.fn((path: string, content: string, mode?: number): void => {
    this.files.set(path, content);
    this.writtenFiles.push({ path, content, ...(mode !== undefined ? { mode } : {}) });
  });

  exists = vi.fn((path: string): boolean => this.files.has(path));

  seed(path: string, content: string): void {
    this.files.set(path, content);
  }
}

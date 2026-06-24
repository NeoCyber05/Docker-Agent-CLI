import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Writable } from "node:stream";
import { Text, render } from "ink";
import React from "react";
import { QueryEngine } from "src/QueryEngine";
import { useInteractionSession } from "src/screens/useInteractionSession";
import { StateStore } from "src/state/StateStore";
import { expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

class Sink extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  _write(_chunk: Buffer | string, _encoding: BufferEncoding, callback: () => void) {
    callback();
  }
}

test("starts a submitted turn", async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "interaction-"));
  fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  let calls = 0;
  const engine = new QueryEngine({
    cwd: tmp,
    stateStore: new StateStore(tmp),
    dockerEngine: new MockDockerEngine() as never,
    composeRunner: new MockComposeRunner(tmp) as never,
    provider: {
      name: "fake",
      stream: async function* () {
        calls++;
        yield { type: "message_stop", stopReason: "end_turn" } as const;
      },
    },
  });
  let session: ReturnType<typeof useInteractionSession> | undefined;
  function Harness() {
    session = useInteractionSession(engine);
    return React.createElement(Text, null, session.phase);
  }
  const stdout = new Sink();
  const stderr = new Sink();
  const app = render(React.createElement(Harness), {
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  await new Promise<void>((resolve) => setImmediate(resolve));
  session?.submit("hello");
  for (let attempt = 0; attempt < 20 && calls === 0; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  expect(calls).toBe(1);
  app.unmount();
  app.cleanup();
  fs.rmSync(tmp, { recursive: true, force: true });
});

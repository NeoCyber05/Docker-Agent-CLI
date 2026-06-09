import { Readable, Writable } from "node:stream";
import { Box, Text, render } from "ink";
import React, { useState, useEffect } from "react";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹"];

function ThinkingIndicator() {
  const [frameIndex, setFrameIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      console.error("interval fired, updating frameIndex");
      setFrameIndex((i) => (i + 1) % SPINNER_FRAMES.length);
      console.error("setFrameIndex called");
    }, 100);
    return () => clearInterval(id);
  }, []);

  const frame = SPINNER_FRAMES[frameIndex] ?? SPINNER_FRAMES[0];
  return React.createElement(Text, { color: "yellow" }, `${frame} Thinking… ${elapsed}s`);
}

class TestStdout extends Writable {
  constructor() {
    super();
    this.columns = 100;
    this.rows = 24;
    this.isTTY = true;
    this.chunks = [];
  }
  _write(chunk, enc, cb) {
    this.chunks.push(String(chunk));
    console.error("stdout write #" + this.chunks.length + " len=" + String(chunk).length);
    cb();
  }
  output() { return this.chunks.join(""); }
}
class TestStdin extends Readable {
  constructor() { super(); this.isTTY = true; }
  setEncoding() { return this; }
  setRawMode() { return this; }
  _read() {}
  ref() { return this; }
  unref() { return this; }
}

const stdin = new TestStdin();
const stdout = new TestStdout();
const stderr = new TestStdout();

const app = render(
  React.createElement(Box, { paddingLeft: 1 },
    React.createElement(ThinkingIndicator)
  ),
  { stdin, stdout, stderr, debug: true, patchConsole: false, exitOnCtrlC: false }
);

await new Promise(r => setImmediate(r));

console.error("After initial render, chunks:", stdout.chunks.length);
const frame1 = stdout.output();

// Simulate vi.advanceTimersByTime(200) by manually firing intervals
// Actually let's just wait 200ms for real
await new Promise(r => setTimeout(r, 250));

console.error("After 250ms, chunks:", stdout.chunks.length);
const frame2 = stdout.output();
console.log("frame1 === frame2:", frame1 === frame2);
console.log("frame1:", JSON.stringify(frame1.slice(0, 100)));
console.log("frame2:", JSON.stringify(frame2.slice(0, 150)));

app.unmount();
app.cleanup();
process.exit(0);

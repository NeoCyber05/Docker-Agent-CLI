import { Text } from "ink";
import type React from "react";
import { useLayoutEffect, useState } from "react";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function ThinkingIndicator(): React.ReactElement {
  const [frameIndex, setFrameIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  // useLayoutEffect runs synchronously during the commit phase so intervals are
  // set up before the test can advance fake timers. In Ink's legacy reconciler,
  // setState called from a timer fires a synchronous re-render (no async scheduler).
  useLayoutEffect(() => {
    const spinnerInterval = setInterval(() => {
      setFrameIndex((i) => (i + 1) % SPINNER_FRAMES.length);
    }, 100);

    return () => {
      clearInterval(spinnerInterval);
    };
  }, []);

  useLayoutEffect(() => {
    const startedAt = Date.now();
    const elapsedInterval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => {
      clearInterval(elapsedInterval);
    };
  }, []);

  const frame = SPINNER_FRAMES[frameIndex] ?? SPINNER_FRAMES[0];

  return (
    <Text color="yellow">
      {frame} Thinking… {elapsed}s
    </Text>
  );
}

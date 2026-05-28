export class AsyncQueue<T> implements AsyncIterable<T> {
  private buffer: T[] = [];
  private waiters: Array<(value: IteratorResult<T>) => void> = [];
  private closed = false;
  private error: Error | null = null;

  push(value: T): void {
    if (this.closed) throw new Error("AsyncQueue: push after close");
    const waiter = this.waiters.shift();
    if (waiter) waiter({ value, done: false });
    else this.buffer.push(value);
  }

  close(): void {
    this.closed = true;
    for (const w of this.waiters) w({ value: undefined as unknown as T, done: true });
    this.waiters = [];
  }

  abort(error: Error): void {
    this.error = error;
    this.closed = true;
    for (const w of this.waiters) w({ value: undefined as unknown as T, done: true });
    this.waiters = [];
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    const queue = this;
    return {
      next(): Promise<IteratorResult<T>> {
        if (queue.buffer.length > 0) {
          return Promise.resolve({ value: queue.buffer.shift() as T, done: false });
        }
        if (queue.closed) {
          if (queue.error) return Promise.reject(queue.error);
          return Promise.resolve({ value: undefined as unknown as T, done: true });
        }
        return new Promise((resolve) => queue.waiters.push(resolve));
      },
      return(): Promise<IteratorResult<T>> {
        return Promise.resolve({ value: undefined as unknown as T, done: true });
      },
    };
  }
}

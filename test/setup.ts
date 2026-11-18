import '@testing-library/jest-dom/vitest';

// jsdom lacks the SSE constructor; the UI only needs a stub for tests.
if (typeof window !== 'undefined' && !('EventSource' in window)) {
  class MockEventSource {
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    constructor(public url: string) {}
    close() {}
  }
  // @ts-expect-error test shim
  window.EventSource = MockEventSource;
}

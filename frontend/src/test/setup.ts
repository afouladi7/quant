import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/** Minimal controllable WebSocket stand-in. Tests drive it via FakeWebSocket.last. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static get last(): FakeWebSocket {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  }
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  emit(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  serverClose() {
    this.onclose?.();
  }
  close() {
    this.closed = true;
  }
}

vi.stubGlobal("WebSocket", FakeWebSocket);

afterEach(() => {
  cleanup();
  FakeWebSocket.instances = [];
  vi.restoreAllMocks();
  localStorage.clear();
});

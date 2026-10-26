// Records the API calls this browser makes, so the How It Works page can show them live.
export interface RecordedCall {
  id: number;
  at: number; // epoch ms
  method: string;
  path: string;
  status: number;
  ms: number;
  requestBody?: unknown;
  responsePreview?: string;
}

const MAX = 60;
let seq = 0;
let calls: RecordedCall[] = []; // replaced (never mutated) so React's useSyncExternalStore sees each change
const listeners = new Set<() => void>();

export function recordCall(c: Omit<RecordedCall, "id">): void {
  calls = [{ ...c, id: ++seq }, ...calls].slice(0, MAX);
  listeners.forEach((l) => l());
}

export function getCalls(): RecordedCall[] {
  return calls;
}

export function subscribeCalls(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

import { useCallback, useEffect, useState } from "react";

// Lesson progress is a per-browser convenience: kept in localStorage, safe if storage is unavailable.
const KEY = "marketlab.lessonsDone";

function read(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function useProgress() {
  const [done, setDone] = useState<Set<string>>(read);
  useEffect(() => {
    const onStorage = () => setDone(read());
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const mark = useCallback((id: string, value = true) => {
    setDone((prev) => {
      const next = new Set(prev);
      if (value) next.add(id); else next.delete(id);
      try { localStorage.setItem(KEY, JSON.stringify([...next])); } catch { /* not persisted */ }
      return next;
    });
  }, []);
  return { done, mark };
}

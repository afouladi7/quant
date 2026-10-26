import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ViewMode = "simple" | "technical";

const KEY = "marketlab.viewMode";
const ViewModeContext = createContext<{ mode: ViewMode; setMode: (m: ViewMode) => void } | null>(null);

function initial(): ViewMode {
  const fromUrl = new URLSearchParams(window.location.search).get("view");
  if (fromUrl === "technical" || fromUrl === "simple") return fromUrl;
  try {
    return localStorage.getItem(KEY) === "technical" ? "technical" : "simple";
  } catch {
    return "simple";
  }
}

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ViewMode>(initial);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* storage unavailable: preference just won't persist */
    }
  }, [mode]);
  return <ViewModeContext.Provider value={{ mode, setMode }}>{children}</ViewModeContext.Provider>;
}

export function useViewMode() {
  const ctx = useContext(ViewModeContext);
  if (!ctx) throw new Error("useViewMode must be used inside <ViewModeProvider>");
  return ctx;
}

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { StreamProvider } from "./api/stream";
import { ViewModeProvider } from "./state/viewMode";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ViewModeProvider>
        <StreamProvider>
          <App />
        </StreamProvider>
      </ViewModeProvider>
    </BrowserRouter>
  </StrictMode>,
);

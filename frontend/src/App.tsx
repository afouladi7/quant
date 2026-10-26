import { Route, Routes } from "react-router-dom";
import { ControlBar } from "./components/ControlBar";
import { Header } from "./components/Header";
import { FX } from "./pages/FX";
import { Home } from "./pages/Home";
import { MarketMaker } from "./pages/MarketMaker";
import { TCPLab } from "./pages/TCPLab";

export function App() {
  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Header />
      <ControlBar />
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/market-maker" element={<MarketMaker />} />
          <Route path="/fx" element={<FX />} />
          <Route path="/tcp-lab" element={<TCPLab />} />
          <Route
            path="*"
            element={
              <div className="page">
                <p className="empty">Page not found.</p>
              </div>
            }
          />
        </Routes>
      </main>
      <footer className="footer muted small">
        Educational simulation · hypothetical prices and trades only · not investment advice
      </footer>
    </div>
  );
}

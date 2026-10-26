import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { ControlBar } from "./components/ControlBar";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { FX } from "./pages/FX";
import { Glossary } from "./pages/Glossary";
import { Home } from "./pages/Home";
import { HowItWorks } from "./pages/HowItWorks";
import { Learn } from "./pages/Learn";
import { MarketMaker } from "./pages/MarketMaker";
import { Options } from "./pages/Options";
import { Playground } from "./pages/Playground";
import { RiskLab } from "./pages/RiskLab";
import { TCPLab } from "./pages/TCPLab";

/** The simulation clock only matters on pages with a live simulation, so the bar appears only there. */
function WithClock({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ControlBar />
      {children}
    </>
  );
}

export function App() {
  const [menu, setMenu] = useState(false);
  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <Header menuOpen={menu} onMenu={() => setMenu(!menu)} />
      <div className="layout">
        <Sidebar open={menu} onNavigate={() => setMenu(false)} />
        <main id="main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/learn" element={<Learn />} />
            <Route path="/learn/:lessonId" element={<Learn />} />
            <Route path="/glossary" element={<Glossary />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/market-maker" element={<WithClock><MarketMaker /></WithClock>} />
            <Route path="/fx" element={<WithClock><FX /></WithClock>} />
            <Route path="/risk" element={<RiskLab />} />
            <Route path="/options" element={<Options />} />
            <Route path="/tcp-lab" element={<TCPLab />} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="*" element={<div className="page"><p className="empty">Page not found.</p></div>} />
          </Routes>
          <footer className="footer muted small">Educational simulation · hypothetical prices and trades only · not investment advice</footer>
        </main>
      </div>
    </div>
  );
}

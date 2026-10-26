import { NavLink } from "react-router-dom";
import { NAV } from "../nav";

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  return (
    <nav id="sidebar" className={`sidebar ${open ? "open" : ""}`} aria-label="Main">
      {NAV.map((g) => (
        <div key={g.title} className="nav-group">
          <div className="nav-group-title">{g.title}</div>
          {g.items.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.to === "/"} onClick={onNavigate} title={i.blurb}>
              <span>{i.label}</span>
              {i.level !== "All levels" && <span className={`lvl lvl-${i.level.toLowerCase()}`}>{i.level}</span>}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  AudioLines,
  BookOpen,
  ChevronDown,
  ChevronsUpDown,
  CircleHelp,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Menu,
  PanelLeftClose,
  Radio,
  Scale,
  Settings2,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  Target,
  Workflow,
  X,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { useModels } from "../contexts/ModelsContext";
const groups = [
  {
    title: "WORKSPACE",
    items: [
      { name: "Overview", path: "/", icon: LayoutDashboard },
      { name: "Playground", path: "/playground", icon: SquareTerminal },
      { name: "Prompt library", path: "/prompts", icon: GitBranch },
      { name: "Knowledge Base", path: "/knowledge-base", icon: BookOpen },
    ],
  },
  {
    title: "EVALUATE",
    items: [
      { name: "Evaluations", path: "/evaluations", icon: FlaskConical },
      { name: "AI Judge", path: "/ai-judge", icon: Scale },
      { name: "Judge Reliability", path: "/judge-reliability", icon: Target },
      { name: "Experiments", path: "/experiments", icon: GitBranch },
      { name: "Agents", path: "/agents", icon: Workflow },
      { name: "Regression Tests", path: "/regression-tests", icon: ListChecks },
    ],
  },
  {
    title: "OBSERVE",
    items: [
      { name: "Traces", path: "/traces", icon: Activity },
      { name: "Monitoring", path: "/monitoring", icon: Radio },
      { name: "Failure Inbox", path: "/failure-inbox", icon: ShieldCheck },
    ],
  },
  {
    title: "SPECIALIZED",
    items: [
      { name: "Security", path: "/security", icon: ShieldCheck },
      { name: "Marketing Evaluation", path: "/marketing", icon: Sparkles },
    ],
  },
];
export function Workspace() {
  const [open, setOpen] = useState(false);
  const { data } = useModels();
  const health = useApi<{ database_engine: string }>("/health");
  return (
    <div className="workspace">
      <button
        className={`sidebar-scrim ${open ? "visible" : ""}`}
        onClick={() => setOpen(false)}
        aria-label="Close navigation"
      />
      <aside className={`sidebar ${open ? "is-open" : ""}`}>
        <div className="brand">
          <div className="brand-symbol">
            <AudioLines size={24} />
          </div>
          <span>
            AURA<span className="brand-dot">.</span>
          </span>
          <button
            className="mobile-close"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
          >
            <X size={20} />
          </button>
          <PanelLeftClose size={16} className="collapse-icon" />
        </div>
        <div className="workspace-select">
          <span className="workspace-avatar">AU</span>
          <div>
            <strong>Local workspace</strong>
            <small>Personal project</small>
          </div>
          <ChevronsUpDown size={14} />
        </div>
        <nav aria-label="Main navigation">
          {groups.map((g) => (
            <div className="nav-group" key={g.title}>
              <div className="nav-label">{g.title}</div>
              {g.items.map((i) => (
                <NavLink
                  end={i.path === "/"}
                  to={i.path}
                  key={i.path}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `nav-item ${isActive ? "active" : ""}`
                  }
                >
                  <i.icon size={17} />
                  <span>{i.name}</span>
                  {i.name === "Evaluations" && (
                    <span className="nav-new">CORE</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span className="status-dot" />
            <strong>Local by design</strong>
            <p>Your models. Your data. Your control.</p>
          </div>
          <NavLink
            to="/settings"
            className="nav-item"
            onClick={() => setOpen(false)}
          >
            <Settings2 size={17} />
            Settings
          </NavLink>
          <a
            href="https://docs.ollama.com/quickstart"
            target="_blank"
            rel="noreferrer"
            className="nav-item"
          >
            <CircleHelp size={17} />
            Ollama documentation
            <ArrowUpRight size={13} />
          </a>
          <div className="profile">
            <span className="profile-avatar">AU</span>
            <div>
              <strong>Local developer</strong>
              <small>Developer</small>
            </div>
            <ChevronDown size={14} />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu"
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={21} />
            </button>
            <span>Workspace</span>
            <span className="slash">/</span>
            <strong>AURA platform</strong>
            <span className="version">v1.0</span>
          </div>
          <div className="topbar-right">
            <span className={`status-dot ${data?.available ? "" : "muted"}`} />
            <span>
              {data?.available ? "Ollama connected" : "Ollama offline"}
            </span>
            <span className="local-badge">LOCAL</span>
          </div>
        </header>
        <main>
          {health.data?.database_engine === "sqlite" && (
            <div className="preview-banner" role="status">
              UI verification preview · isolated SQLite test database.
              PostgreSQL and real model inference are not verified.
            </div>
          )}
          <Outlet />
        </main>
        <footer>
          <span>AURA · AI Reliability & Evaluation Platform</span>
          <span>
            <span className="status-dot" /> Built for better AI
          </span>
        </footer>
      </div>
    </div>
  );
}

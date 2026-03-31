import { useNavigate } from "react-router-dom";
import {
  Plus,
  TerminalSquare,
  FolderGit2,
  GitBranch,
  Menu,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";
import { useStore } from "../store";
import * as api from "../api";
import ClaudeAuth from "./ClaudeAuth";
import ModelSelector from "./ModelSelector";
import PersonaSelector from "./PersonaSelector";
import ThemeSelector from "./ThemeSelector";

export default function TopBar() {
  const navigate = useNavigate();
  const selectedRepo = useStore((s) => s.selectedRepo);
  const repos = useStore((s) => s.repos);
  const toggleTerminal = useStore((s) => s.toggleTerminal);
  const terminalOpen = useStore((s) => s.terminalOpen);
  const toggleRightPanel = useStore((s) => s.toggleRightPanel);
  const rightPanelOpen = useStore((s) => s.rightPanelOpen);
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  const repoContext = useStore((s) => s.repoContext);
  const claudeAuth = useStore((s) => s.claudeAuth);
  const isAuthed = claudeAuth.authenticated;
  const [refreshing, setRefreshing] = useState(false);

  const currentRepo = repos.find((r) => r.name === selectedRepo);
  const isDirty = currentRepo?.dirty ?? false;

  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b border-border-subtle bg-bg-primary px-2 sm:gap-2 sm:px-3">
      {/* Mobile sidebar toggle */}
      {isAuthed && selectedRepo && (
        <button
          onClick={toggleSidebar}
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors md:hidden"
          title="Toggle sidebar"
        >
          <Menu size={18} />
        </button>
      )}
      {/* Left: brand */}
      <span
        className="font-display text-sm font-bold tracking-wide text-text-primary select-none cursor-pointer"
        onClick={() => navigate("/")}
      >
        <span className="hidden sm:inline">DEATHSTAR</span>
        <span className="sm:hidden">DS</span>
      </span>

      <ThemeSelector />

      <div className="mx-1 h-4 w-px bg-border-subtle" />

      {/* LLM / chat controls — left side */}
      <ClaudeAuth />
      {selectedRepo && <ModelSelector />}
      {selectedRepo && <PersonaSelector />}
      {selectedRepo && (
        <button
          onClick={() => navigate(`/${encodeURIComponent(selectedRepo)}`)}
          className="flex h-7 items-center gap-1 rounded-md border border-border-subtle px-2 text-xs font-medium text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
          title="New conversation"
        >
          <Plus size={14} />
          <span className="hidden sm:inline">New</span>
        </button>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right side: repo + tools */}
      {selectedRepo && (
        <button
          onClick={toggleRightPanel}
          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors ${
            rightPanelOpen
              ? "bg-accent-muted text-accent"
              : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
          }`}
          title="Toggle repo panel"
        >
          <FolderGit2 size={14} />
          <span className="hidden sm:inline max-w-[100px] truncate font-medium">
            {selectedRepo}
          </span>
          {repoContext?.branch && (
            <>
              <GitBranch size={10} className="text-text-muted" />
              <span className="hidden md:inline max-w-[80px] truncate font-mono text-text-muted">
                {repoContext.branch}
              </span>
            </>
          )}
          {isDirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-warning" title="Uncommitted changes" />
          )}
        </button>
      )}

      {selectedRepo && (
        <button
          onClick={async () => {
            setRefreshing(true);
            const s = useStore.getState();
            await Promise.allSettled([
              s.loadRepos(),
              s.loadCommits(),
              s.loadBranches(),
              s.loadPullRequests(),
              selectedRepo
                ? api.fetchRepoContext(selectedRepo).then((ctx) => useStore.setState({ repoContext: ctx }))
                : Promise.resolve(),
            ]);
            setRefreshing(false);
          }}
          disabled={refreshing}
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors disabled:opacity-50"
          title="Refresh repo state"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
        </button>
      )}

      {selectedRepo && (
        <button
          onClick={toggleTerminal}
          className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${
            terminalOpen
              ? "bg-accent-muted text-accent"
              : "text-text-muted hover:bg-bg-hover hover:text-text-secondary"
          }`}
          title="Toggle terminal"
        >
          <TerminalSquare size={16} />
        </button>
      )}

    </header>
  );
}

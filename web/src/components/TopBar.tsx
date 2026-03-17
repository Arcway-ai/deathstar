import {
  GitBranch,
  Menu,
  Plus,
  Settings,
  ChevronDown,
} from "lucide-react";
import { useStore } from "../store";
import PersonaSelector from "./PersonaSelector";

export default function TopBar() {
  const selectedRepo = useStore((s) => s.selectedRepo);
  const repoContext = useStore((s) => s.repoContext);
  const repos = useStore((s) => s.repos);
  const selectRepo = useStore((s) => s.selectRepo);
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  const toggleSettings = useStore((s) => s.toggleSettings);
  const newConversation = useStore((s) => s.newConversation);

  const currentRepo = repos.find((r) => r.name === selectedRepo);

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border-subtle bg-bg-primary px-3">
      {/* Left: hamburger + brand */}
      <button
        onClick={toggleSidebar}
        className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
        title="Toggle sidebar"
      >
        <Menu size={18} />
      </button>

      <span className="font-display text-sm font-bold tracking-wide text-text-primary select-none">
        DEATHSTAR
      </span>

      <div className="mx-2 h-4 w-px bg-border-subtle" />

      {/* Repo selector dropdown */}
      {selectedRepo && (
        <div className="relative group">
          <button className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors">
            <span className="max-w-[120px] truncate">{selectedRepo}</span>
            <ChevronDown size={12} />
          </button>
          <div className="invisible absolute left-0 top-full z-50 mt-1 min-w-[200px] rounded-lg border border-border-subtle bg-bg-surface p-1 shadow-xl group-hover:visible">
            {repos.map((r) => (
              <button
                key={r.name}
                onClick={() => selectRepo(r.name)}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors ${
                  r.name === selectedRepo
                    ? "bg-accent-muted text-accent"
                    : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                }`}
              >
                <span className="truncate">{r.name}</span>
                {r.dirty && (
                  <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Branch indicator */}
      {currentRepo && (
        <div className="flex items-center gap-1 rounded-md bg-bg-surface px-2 py-1">
          <GitBranch size={12} className="text-text-muted" />
          <span className="text-xs font-mono text-text-secondary">
            {repoContext?.branch ?? currentRepo.branch}
          </span>
          {currentRepo.dirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-warning" title="Uncommitted changes" />
          )}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Persona selector */}
      {selectedRepo && <PersonaSelector />}

      {/* New conversation */}
      {selectedRepo && (
        <button
          onClick={newConversation}
          className="flex h-7 items-center gap-1 rounded-md border border-border-subtle px-2 text-xs font-medium text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
          title="New conversation"
        >
          <Plus size={14} />
          <span className="hidden sm:inline">New</span>
        </button>
      )}

      {/* Settings */}
      <button
        onClick={toggleSettings}
        className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
        title="Settings"
      >
        <Settings size={16} />
      </button>
    </header>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  FolderTree,
  GitCommitHorizontal,
  X,
  ChevronRight,
  Folder,
  FolderOpen,
  FileText,
  RefreshCw,
  Copy,
  Check,
  Save,
  ChevronDown,
  Search,
} from "lucide-react";
import { useStore } from "../store";
import { buildTree } from "../fileTree";
import { characterAvatarUrl } from "../avatars";
import type { TreeNode } from "../fileTree";
import type { RightPanelView } from "../types";
import BranchSelector from "./BranchSelector";

const tabs: { id: RightPanelView; icon: typeof FolderTree; label: string }[] = [
  { id: "files", icon: FolderTree, label: "Files" },
  { id: "commits", icon: GitCommitHorizontal, label: "Commits" },
];

export default function RepoPanel() {
  const navigate = useNavigate();
  const open = useStore((s) => s.rightPanelOpen);
  const view = useStore((s) => s.rightPanelView);
  const setRightPanelView = useStore((s) => s.setRightPanelView);
  const toggleRightPanel = useStore((s) => s.toggleRightPanel);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const repos = useStore((s) => s.repos);
  const quickSave = useStore((s) => s.quickSave);

  const currentRepo = repos.find((r) => r.name === selectedRepo);
  const isDirty = currentRepo?.dirty ?? false;
  const [repoDropdownOpen, setRepoDropdownOpen] = useState(false);
  const repoDropdownRef = useRef<HTMLDivElement>(null);

  // Close repo dropdown on click outside
  useEffect(() => {
    if (!repoDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (repoDropdownRef.current && !repoDropdownRef.current.contains(e.target as Node)) {
        setRepoDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [repoDropdownOpen]);

  if (!open || !selectedRepo) return null;

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/50 md:hidden"
        onClick={toggleRightPanel}
      />
      <aside className="absolute right-0 top-0 z-40 flex h-full w-80 flex-col border-l border-border-subtle bg-bg-primary animate-slide-right md:relative md:animate-none">
        {/* Repo header */}
        <div className="border-b border-border-subtle px-3 py-2">
          <div className="flex items-center justify-between mb-1.5">
            {/* Repo dropdown */}
            <div ref={repoDropdownRef} className="relative">
              <button
                onClick={() => setRepoDropdownOpen(!repoDropdownOpen)}
                className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium text-text-primary hover:bg-bg-hover transition-colors"
              >
                <span className="max-w-[160px] truncate font-display font-bold text-sm">
                  {selectedRepo}
                </span>
                <ChevronDown size={12} className="text-text-muted" />
              </button>
              {repoDropdownOpen && (
                <div className="absolute left-0 top-full z-50 mt-1 min-w-[200px] rounded-lg border border-border-subtle bg-bg-surface p-1 shadow-xl animate-fade-in">
                  {repos.map((r) => (
                    <button
                      key={r.name}
                      onClick={() => {
                        navigate(`/${encodeURIComponent(r.name)}`);
                        setRepoDropdownOpen(false);
                      }}
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
              )}
            </div>

            <button
              onClick={toggleRightPanel}
              className="flex h-6 w-6 items-center justify-center rounded text-text-muted hover:text-text-secondary transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          {/* Branch + Save row */}
          <div className="flex items-center gap-1.5">
            <BranchSelector />
            <button
              onClick={quickSave}
              disabled={!isDirty}
              className={`flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors ${
                isDirty
                  ? "border border-warning/50 bg-warning/10 text-warning hover:bg-warning/20"
                  : "text-text-muted opacity-40 cursor-default"
              }`}
              title={isDirty ? "Save changes (Cmd+S)" : "No changes to save"}
            >
              <Save size={12} />
              Save
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex items-center border-b border-border-subtle">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setRightPanelView(tab.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors ${
                view === tab.id
                  ? "border-b-2 border-accent text-accent"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-2">
          {view === "files" && <FileTreePanel />}
          {view === "commits" && <CommitsPanel />}
        </div>
      </aside>
    </>
  );
}

/* ── File Tree ────────────────────────────────────────────────── */

function FileTreePanel() {
  const selectedRepo = useStore((s) => s.selectedRepo);
  const fileTree = useStore((s) => s.fileTree);
  const fileContent = useStore((s) => s.fileContent);
  const openFile = useStore((s) => s.openFile);
  const loadFileTree = useStore((s) => s.loadFileTree);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectedRepo && fileTree.length === 0) {
      setLoading(true);
      loadFileTree(selectedRepo).finally(() => setLoading(false));
    }
  }, [selectedRepo, fileTree.length, loadFileTree]);

  // Cmd+P / Ctrl+P to focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Fuzzy-ish search: split query into terms, all must match the path
  const filtered = useMemo(() => {
    if (!query.trim()) return null;
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    return fileTree.filter((path) => {
      const lower = path.toLowerCase();
      return terms.every((t) => lower.includes(t));
    });
  }, [query, fileTree]);

  if (!selectedRepo) {
    return (
      <p className="px-2 py-8 text-center text-xs text-text-muted">
        Select a repo first
      </p>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <RefreshCw size={14} className="animate-spin text-text-muted" />
        <span className="ml-2 text-xs text-text-muted">Loading...</span>
      </div>
    );
  }

  if (fileTree.length === 0) {
    return (
      <button
        onClick={() => {
          setLoading(true);
          loadFileTree(selectedRepo).finally(() => setLoading(false));
        }}
        className="mx-auto mt-8 block rounded-md border border-border-subtle px-3 py-1.5 text-xs text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
      >
        Load file tree
      </button>
    );
  }

  const tree = buildTree(fileTree);
  const activePath = fileContent?.path ?? null;

  return (
    <div>
      {/* Search input */}
      <div className="relative mb-2">
        <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
        <input
          ref={searchRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setQuery(""); searchRef.current?.blur(); }
            // Enter opens first result
            if (e.key === "Enter" && filtered && filtered.length > 0 && filtered[0]) {
              openFile(selectedRepo, filtered[0]);
              setQuery("");
            }
          }}
          placeholder="Search files…  ⌘P"
          className="w-full rounded-md border border-border-subtle bg-bg-primary py-1.5 pl-7 pr-2 text-[11px] text-text-primary placeholder:text-text-muted/60 focus:border-accent focus:outline-none transition-colors"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-text-secondary"
          >
            <X size={10} />
          </button>
        )}
      </div>

      {/* Search results (flat list) */}
      {filtered !== null ? (
        <div>
          <div className="flex items-center justify-between px-1 pb-1">
            <span className="text-[10px] text-text-muted">
              {filtered.length} result{filtered.length !== 1 ? "s" : ""}
            </span>
          </div>
          {filtered.length === 0 ? (
            <p className="px-2 py-4 text-center text-[11px] text-text-muted">
              No files match &ldquo;{query}&rdquo;
            </p>
          ) : (
            <div className="space-y-px">
              {filtered.slice(0, 50).map((path) => {
                const fileName = path.split("/").pop() ?? path;
                const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
                const isActive = activePath === path;
                return (
                  <button
                    key={path}
                    onClick={() => { openFile(selectedRepo, path); setQuery(""); }}
                    className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[11px] transition-colors ${
                      isActive
                        ? "bg-accent-muted text-accent"
                        : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                    }`}
                  >
                    <FileText size={11} className={`shrink-0 ${isActive ? "text-accent" : "text-text-muted"}`} />
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{fileName}</span>
                      {dir && <span className="ml-1.5 text-text-muted">{dir}</span>}
                    </span>
                  </button>
                );
              })}
              {filtered.length > 50 && (
                <p className="px-2 py-1 text-[10px] text-text-muted">
                  +{filtered.length - 50} more…
                </p>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Normal tree view */
        <div>
          <div className="flex items-center justify-between px-1 pb-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wider text-text-muted">
              {selectedRepo}
            </span>
            <button
              onClick={() => {
                setLoading(true);
                loadFileTree(selectedRepo).finally(() => setLoading(false));
              }}
              className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
              title="Refresh"
            >
              <RefreshCw size={10} />
            </button>
          </div>

          <div className="space-y-px">
            {tree.map((node) => (
              <TreeNodeRow
                key={node.path}
                node={node}
                depth={0}
                activePath={activePath}
                repo={selectedRepo}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TreeNodeRow({
  node,
  depth,
  activePath,
  repo,
}: {
  node: TreeNode;
  depth: number;
  activePath: string | null;
  repo: string;
}) {
  const openFile = useStore((s) => s.openFile);
  const [expanded, setExpanded] = useState(depth < 1);

  const isActive = activePath === node.path;
  const paddingLeft = 4 + depth * 14;

  if (node.isDir) {
    return (
      <>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-1 rounded py-[3px] text-left text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          style={{ paddingLeft }}
        >
          <ChevronRight
            size={10}
            className={`shrink-0 text-text-muted transition-transform duration-150 ${
              expanded ? "rotate-90" : ""
            }`}
          />
          {expanded ? (
            <FolderOpen size={12} className="shrink-0 text-accent/70" />
          ) : (
            <Folder size={12} className="shrink-0 text-accent/70" />
          )}
          <span className="truncate font-medium">{node.name}</span>
        </button>

        {expanded && (
          <div>
            {node.children.map((child) => (
              <TreeNodeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                activePath={activePath}
                repo={repo}
              />
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <button
      onClick={() => openFile(repo, node.path)}
      className={`flex w-full items-center gap-1 rounded py-[3px] text-left font-mono text-[11px] transition-colors ${
        isActive
          ? "bg-accent-muted text-accent"
          : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
      }`}
      style={{ paddingLeft: paddingLeft + 10 }}
    >
      <FileText
        size={11}
        className={`shrink-0 ${isActive ? "text-accent" : "text-text-muted"}`}
      />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

/* ── Commits ──────────────────────────────────────────────────── */

function CommitsPanel() {
  const selectedRepo = useStore((s) => s.selectedRepo);
  const commits = useStore((s) => s.commits);
  const commitsLoading = useStore((s) => s.commitsLoading);
  const loadCommits = useStore((s) => s.loadCommits);
  const repoContext = useStore((s) => s.repoContext);
  const [copiedSha, setCopiedSha] = useState<string | null>(null);

  useEffect(() => {
    if (selectedRepo && commits.length === 0) {
      loadCommits();
    }
  }, [selectedRepo, commits.length, loadCommits]);

  if (!selectedRepo) {
    return (
      <p className="px-2 py-8 text-center text-xs text-text-muted">
        Select a repo first
      </p>
    );
  }

  if (commitsLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <RefreshCw size={14} className="animate-spin text-text-muted" />
        <span className="ml-2 text-xs text-text-muted">Loading...</span>
      </div>
    );
  }

  const copySha = (sha: string) => {
    navigator.clipboard.writeText(sha).then(() => {
      setCopiedSha(sha);
      setTimeout(() => setCopiedSha(null), 1500);
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between px-1 pb-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-text-muted">
          {repoContext?.branch ?? "commits"}
        </span>
        <button
          onClick={loadCommits}
          className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
          title="Refresh"
        >
          <RefreshCw size={10} />
        </button>
      </div>

      {commits.length === 0 ? (
        <p className="px-2 py-8 text-center text-xs text-text-muted">
          No commits on this branch
        </p>
      ) : (
        <div className="space-y-px">
          {commits.map((c) => (
            <div
              key={c.sha}
              className="group rounded-md px-2 py-1.5 hover:bg-bg-hover transition-colors"
            >
              <div className="flex items-start gap-2">
                <img
                  src={characterAvatarUrl(c.author)}
                  alt={c.author}
                  className="mt-0.5 h-6 w-6 shrink-0 rounded"
                  title={c.author}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-text-secondary group-hover:text-text-primary">
                    {c.message}
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <button
                      onClick={() => copySha(c.sha)}
                      className="flex items-center gap-1 font-mono text-[10px] text-accent/70 hover:text-accent transition-colors"
                      title="Copy full SHA"
                    >
                      {copiedSha === c.sha ? (
                        <Check size={8} className="text-success" />
                      ) : (
                        <Copy size={8} className="opacity-0 group-hover:opacity-100" />
                      )}
                      {c.short_sha}
                    </button>
                    <span className="text-[10px] text-text-muted">
                      {c.author}
                    </span>
                    <span className="text-[10px] text-text-muted">
                      {formatCommitDate(c.date)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatCommitDate(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

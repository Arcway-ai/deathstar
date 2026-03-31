import { useState, useRef, useEffect } from "react";
import { GitBranch, Plus, Check, Loader2, Trash2, RefreshCw } from "lucide-react";
import { useStore } from "../store";

export default function BranchSelector() {
  const repoContext = useStore((s) => s.repoContext);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const repos = useStore((s) => s.repos);
  const branches = useStore((s) => s.branches);
  const branchLoading = useStore((s) => s.branchLoading);
  const loadBranches = useStore((s) => s.loadBranches);
  const switchBranch = useStore((s) => s.switchBranch);
  const createAndSwitchBranch = useStore((s) => s.createAndSwitchBranch);
  const deleteBranch = useStore((s) => s.deleteBranch);
  const syncBranch = useStore((s) => s.syncBranch);

  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [inlineCreate, setInlineCreate] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [switching, setSwitching] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inlineInputRef = useRef<HTMLInputElement>(null);

  const currentRepo = repos.find((r) => r.name === selectedRepo);
  const currentBranch = repoContext?.branch ?? currentRepo?.branch ?? "unknown";
  const isDirty = currentRepo?.dirty ?? false;

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
        setInlineCreate(false);
        setError(null);
      }
    }
    if (open || inlineCreate) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open, inlineCreate]);

  // Focus input when creating
  useEffect(() => {
    if (creating) inputRef.current?.focus();
  }, [creating]);

  // Focus inline input
  useEffect(() => {
    if (inlineCreate) inlineInputRef.current?.focus();
  }, [inlineCreate]);

  const handleOpen = () => {
    setOpen(!open);
    setCreating(false);
    setInlineCreate(false);
    setError(null);
    if (!open) loadBranches();
  };

  const handleSwitch = async (branch: string) => {
    if (branch === currentBranch || isDirty) return;
    setSwitching(branch);
    setError(null);
    try {
      await switchBranch(branch);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to switch branch");
    } finally {
      setSwitching(null);
    }
  };

  const handleCreate = async () => {
    const name = newBranchName.trim();
    if (!name) return;
    setSwitching(name);
    setError(null);
    try {
      await createAndSwitchBranch(name);
      setNewBranchName("");
      setCreating(false);
      setInlineCreate(false);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create branch");
    } finally {
      setSwitching(null);
    }
  };

  const handleDelete = async (branch: string) => {
    if (isDirty) return;
    if (!confirm(`Delete branch "${branch}"? This cannot be undone.`)) return;
    setDeleting(branch);
    setError(null);
    try {
      await deleteBranch(branch);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete branch");
    } finally {
      setDeleting(null);
    }
  };

  const handleSync = async () => {
    if (isDirty) return;
    setSyncing(true);
    setError(null);
    try {
      const defaultBranch = branches.find((b) => b === "main" || b === "master") ?? "main";
      await syncBranch(defaultBranch);
      if (isDefault(currentBranch)) {
        setOpen(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const isDefault = (b: string) => b === "main" || b === "master";

  const onDefaultBranch = isDefault(currentBranch);

  if (!currentRepo) return null;

  return (
    <div className="relative" ref={dropdownRef}>
      <div className="flex items-center gap-1">
        <button
          onClick={handleOpen}
          className="flex items-center gap-1.5 rounded-md bg-bg-surface px-2 py-1 text-xs hover:bg-bg-hover transition-colors"
          title="Switch branch"
        >
          <GitBranch size={12} className="text-text-muted" />
          <span className="font-mono text-text-secondary max-w-[100px] truncate">
            {currentBranch}
          </span>
          {isDirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-warning" title="Uncommitted changes" />
          )}
        </button>
        <button
          onClick={() => { setInlineCreate(!inlineCreate); setError(null); setNewBranchName(""); }}
          className="flex h-6 w-6 items-center justify-center rounded-md text-text-muted hover:text-accent hover:bg-bg-hover transition-colors"
          title="New branch"
        >
          <Plus size={12} />
        </button>
        {onDefaultBranch && !isDirty && (
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex h-6 items-center gap-1 rounded-md px-1.5 text-[10px] text-text-muted hover:text-accent hover:bg-bg-hover transition-colors disabled:opacity-50"
            title="Pull latest from origin"
          >
            <RefreshCw size={10} className={syncing ? "animate-spin" : ""} />
          </button>
        )}
      </div>

      {/* Inline new-branch input (no dropdown needed) */}
      {inlineCreate && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-border-subtle bg-bg-surface p-2 shadow-xl animate-fade-in">
          <div className="flex gap-1.5">
            <input
              ref={inlineInputRef}
              type="text"
              value={newBranchName}
              onChange={(e) => setNewBranchName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") { setInlineCreate(false); setNewBranchName(""); }
              }}
              placeholder="new-branch-name"
              className="flex-1 rounded-md border border-border-subtle bg-bg-primary px-2 py-1 text-xs font-mono text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            <button
              onClick={handleCreate}
              disabled={!newBranchName.trim() || switching !== null}
              className="rounded-md bg-accent px-2 py-1 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 transition-colors"
            >
              {switching === newBranchName.trim() ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                "Create"
              )}
            </button>
          </div>
          <p className="mt-1 text-[10px] text-text-muted">
            Branch from <span className="font-mono">{currentBranch}</span>
          </p>
          {error && <p className="mt-1 text-[10px] text-red-400">{error}</p>}
        </div>
      )}

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-border-subtle bg-bg-surface shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
            <span className="text-xs font-medium text-text-secondary">Branches</span>
            <div className="flex items-center gap-1">
              <button
                onClick={handleSync}
                disabled={syncing || isDirty}
                className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs transition-colors ${
                  isDirty
                    ? "text-text-muted opacity-40 cursor-not-allowed"
                    : "text-text-secondary hover:text-accent hover:bg-bg-hover disabled:opacity-50"
                }`}
                title={isDirty ? "Save changes before syncing" : onDefaultBranch ? "Pull latest from origin" : "Rebase onto origin/main"}
              >
                <RefreshCw size={12} className={syncing ? "animate-spin" : ""} />
                {onDefaultBranch ? "Pull" : "Sync"}
              </button>
              <button
                onClick={() => { setCreating(!creating); setError(null); }}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-accent hover:bg-bg-hover transition-colors"
              >
                <Plus size={12} />
                New
              </button>
            </div>
          </div>

          {/* Create new branch input */}
          {creating && (
            <div className="border-b border-border-subtle px-3 py-2">
              <div className="flex gap-1.5">
                <input
                  ref={inputRef}
                  type="text"
                  value={newBranchName}
                  onChange={(e) => setNewBranchName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  placeholder="new-branch-name"
                  className="flex-1 rounded-md border border-border-subtle bg-bg-primary px-2 py-1 text-xs font-mono text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                />
                <button
                  onClick={handleCreate}
                  disabled={!newBranchName.trim() || switching !== null}
                  className="rounded-md bg-accent px-2 py-1 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 transition-colors"
                >
                  {switching === newBranchName.trim() ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    "Create"
                  )}
                </button>
              </div>
              <p className="mt-1 text-[10px] text-text-muted">
                Branch from <span className="font-mono">{currentBranch}</span>
              </p>
            </div>
          )}

          {/* Dirty warning */}
          {isDirty && !creating && (
            <div className="border-b border-border-subtle px-3 py-1.5">
              <p className="text-[10px] text-warning">
                Save your changes before switching branches, syncing, or deleting.
              </p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="border-b border-border-subtle px-3 py-1.5">
              <p className="text-[10px] text-red-400">{error}</p>
            </div>
          )}

          {/* Branch list */}
          <div className="max-h-48 overflow-y-auto p-1">
            {branchLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 size={14} className="animate-spin text-text-muted" />
              </div>
            ) : branches.length === 0 ? (
              <p className="px-3 py-2 text-xs text-text-muted">No branches found</p>
            ) : (
              branches.map((branch) => (
                <div
                  key={branch}
                  className={`group flex items-center rounded-md transition-colors ${
                    branch === currentBranch
                      ? "bg-accent-muted text-accent"
                      : isDirty
                        ? "text-text-muted"
                        : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                  }`}
                >
                  <button
                    onClick={() => handleSwitch(branch)}
                    disabled={switching !== null || deleting !== null || (isDirty && branch !== currentBranch)}
                    className="flex flex-1 items-center gap-2 px-3 py-1.5 text-left text-xs min-w-0 disabled:cursor-not-allowed"
                  >
                    {switching === branch ? (
                      <Loader2 size={12} className="animate-spin shrink-0" />
                    ) : branch === currentBranch ? (
                      <Check size={12} className="shrink-0" />
                    ) : (
                      <span className="w-3 shrink-0" />
                    )}
                    <span className="font-mono truncate">{branch}</span>
                    {isDefault(branch) && (
                      <span className="ml-auto shrink-0 rounded bg-bg-hover px-1 py-0.5 text-[10px] text-text-muted">
                        default
                      </span>
                    )}
                  </button>
                  {!isDefault(branch) && branch !== currentBranch && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(branch); }}
                      disabled={deleting !== null || switching !== null || isDirty}
                      className={`shrink-0 px-2 py-1.5 transition-all ${
                        isDirty
                          ? "text-text-muted opacity-0"
                          : "text-text-muted opacity-0 group-hover:opacity-100 hover:text-error"
                      }`}
                      title={isDirty ? "Save changes first" : `Delete ${branch}`}
                    >
                      {deleting === branch ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Trash2 size={11} />
                      )}
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

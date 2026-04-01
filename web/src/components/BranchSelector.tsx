import { useState, useRef, useEffect, useMemo } from "react";
import { GitBranch, Plus, Check, Loader2, Trash2, RefreshCw, GitPullRequest, ExternalLink } from "lucide-react";
import { useStore } from "../store";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";

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
  const pullRequests = useStore((s) => s.pullRequests);

  const branchPRMap = useMemo(() => {
    const map = new Map<string, { number: number; url: string; draft: boolean }>();
    for (const pr of pullRequests) {
      if (pr.state === "open") {
        map.set(pr.head_branch, { number: pr.number, url: pr.url, draft: pr.draft });
      }
    }
    return map;
  }, [pullRequests]);

  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [inlineCreate, setInlineCreate] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [switching, setSwitching] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inlineInputRef = useRef<HTMLInputElement>(null);

  const currentRepo = repos.find((r) => r.name === selectedRepo);
  const currentBranch = repoContext?.branch ?? currentRepo?.branch ?? "unknown";

  useEffect(() => {
    if (creating) inputRef.current?.focus();
  }, [creating]);

  useEffect(() => {
    if (inlineCreate) inlineInputRef.current?.focus();
  }, [inlineCreate]);

  const handleSwitch = async (branch: string) => {
    if (branch === currentBranch) return;
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
    <div className="flex items-center gap-1">
      {/* Main branch dropdown */}
      <Popover
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (v) { setInlineCreate(false); setCreating(false); setError(null); loadBranches(); }
        }}
      >
        <PopoverTrigger className="flex items-center gap-1.5 rounded-md bg-bg-surface px-2 py-1 text-xs hover:bg-bg-hover transition-colors">
          <GitBranch size={12} className="text-text-muted" />
          <span className="font-mono text-text-secondary max-w-[100px] truncate">
            {currentBranch}
          </span>
        </PopoverTrigger>

        <PopoverContent align="start" className="w-64 gap-0 p-0 border-border-subtle bg-bg-surface">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
            <span className="text-xs font-medium text-text-secondary">Branches</span>
            <div className="flex items-center gap-1">
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-text-secondary hover:text-accent hover:bg-bg-hover disabled:opacity-50 transition-colors"
                title={onDefaultBranch ? "Pull latest from origin" : "Rebase onto origin/main"}
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
                      : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                  }`}
                >
                  <button
                    onClick={() => handleSwitch(branch)}
                    disabled={switching !== null || deleting !== null}
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
                    {branchPRMap.has(branch) && (
                      <a
                        href={branchPRMap.get(branch)!.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="ml-auto shrink-0 flex items-center gap-0.5 rounded bg-accent/15 px-1 py-0.5 text-[10px] text-accent hover:bg-accent/25 transition-colors"
                        title={`Open PR #${branchPRMap.get(branch)!.number}${branchPRMap.get(branch)!.draft ? " (draft)" : ""}`}
                      >
                        <GitPullRequest size={9} />
                        #{branchPRMap.get(branch)!.number}
                        <ExternalLink size={8} />
                      </a>
                    )}
                    {isDefault(branch) && (
                      <Badge variant="secondary" className={`${branchPRMap.has(branch) ? "" : "ml-auto "}h-4 shrink-0 px-1 text-[10px] text-text-muted`}>
                        default
                      </Badge>
                    )}
                  </button>
                  {!isDefault(branch) && branch !== currentBranch && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(branch); }}
                      disabled={deleting !== null || switching !== null}
                      className="shrink-0 px-2 py-1.5 text-text-muted opacity-0 group-hover:opacity-100 hover:text-error transition-all"
                      title={`Delete ${branch}`}
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
        </PopoverContent>
      </Popover>

      {/* PR badge for current branch */}
      {branchPRMap.has(currentBranch) && (
        <a
          href={branchPRMap.get(currentBranch)!.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-0.5 rounded bg-accent/15 px-1 py-0.5 text-[10px] text-accent hover:bg-accent/25 transition-colors"
          title={`PR #${branchPRMap.get(currentBranch)!.number}${branchPRMap.get(currentBranch)!.draft ? " (draft)" : ""}`}
        >
          <GitPullRequest size={9} />
          #{branchPRMap.get(currentBranch)!.number}
        </a>
      )}

      {/* Inline create branch */}
      <Popover
        open={inlineCreate}
        onOpenChange={(v) => {
          setInlineCreate(v);
          if (v) { setOpen(false); setError(null); setNewBranchName(""); }
        }}
      >
        <PopoverTrigger
          className="flex h-6 w-6 items-center justify-center rounded-md text-text-muted hover:text-accent hover:bg-bg-hover transition-colors"
          title="New branch"
        >
          <Plus size={12} />
        </PopoverTrigger>

        <PopoverContent align="start" className="w-64 gap-0 p-2 border-border-subtle bg-bg-surface">
          <div className="flex gap-1.5">
            <input
              ref={inlineInputRef}
              type="text"
              value={newBranchName}
              onChange={(e) => setNewBranchName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") setInlineCreate(false);
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
        </PopoverContent>
      </Popover>

      {onDefaultBranch && (
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
  );
}

import { useEffect, useState } from "react";
import { AlertTriangle, Archive, Brain, ExternalLink, GitMerge, GitPullRequest, Globe, Loader2, RefreshCw, ScanSearch, Square, Trash2, X, Zap } from "lucide-react";
import { useStore } from "../store";
import SuggestMemoriesDialog from "./SuggestMemoriesDialog";
import type { PreviewDeployment, ServerQueueItem } from "../types";

/**
 * Contextual action bar above the input.
 *
 * Buttons are grouped into two logical sections:
 *   1. **Agent actions** — control the running agent (Compact, Memories, Nudge, Stop, Start Review)
 *   2. **GitHub / Deploy actions** — repo-level operations (Make PR, Merge, Deploy Preview)
 *
 * A thin separator divides the groups visually.
 * All buttons are always visible but disabled when not applicable.
 */
export default function ActionBar() {
  const sending = useStore((s) => s.sending);
  const compacting = useStore((s) => s.compacting);
  const workflow = useStore((s) => s.workflow);
  const repoContext = useStore((s) => s.repoContext);
  const selectedPR = useStore((s) => s.selectedPR);
  const sendMessage = useStore((s) => s.sendMessage);
  const serverQueue = useStore((s) => s.serverQueue);
  const clearQueue = useStore((s) => s.clearQueue);
  const cancelQueueItem = useStore((s) => s.cancelQueueItem);
  const agentStream = useStore((s) => s.agentStream);
  const fireSuperlaser = useStore((s) => s.fireSuperlaser);
  const conversationId = useStore((s) => s.conversationId);
  const pokeAgent = useStore((s) => s.pokeAgent);
  const interruptAgent = useStore((s) => s.interruptAgent);
  const pullRequests = useStore((s) => s.pullRequests);
  const fetchMemorySuggestions = useStore((s) => s.fetchMemorySuggestions);
  const suggestingMemories = useStore((s) => s.suggestingMemories);
  const activeConversation = useStore((s) => s.activeConversation);
  const createPreview = useStore((s) => s.createPreview);
  const previews = useStore((s) => s.previews);
  const deletePreview = useStore((s) => s.deletePreview);
  const refreshPreview = useStore((s) => s.refreshPreview);
  const previewProvidersConfigured = useStore((s) => s.previewProvidersConfigured);
  const syncBranch = useStore((s) => s.syncBranch);
  const setWorkflow = useStore((s) => s.setWorkflow);

  const currentBranch = repoContext?.branch;
  const isOnFeatureBranch = currentBranch && currentBranch !== "main" && currentBranch !== "master";
  const isAgentActive = sending && !agentStream.pendingPermission;
  const isBusy = isAgentActive || compacting;

  // Check if current branch already has an open PR
  const branchPR = currentBranch
    ? pullRequests.find((pr) => pr.state === "open" && pr.head_branch === currentBranch)
    : null;

  // Agent action flags
  const canCompact = !!conversationId && !compacting;
  const canSuggestMemories = !!conversationId && !suggestingMemories && !!activeConversation?.messages?.length;
  const canStartReview = !!(workflow === "review" && selectedPR !== null && !sending);
  const canNudge = isAgentActive;
  const canStop = isAgentActive;

  // GitHub / Deploy action flags
  const canMakePR = !!(workflow === "patch" && isOnFeatureBranch && conversationId && !sending);
  const canMerge = !!(branchPR && conversationId && !sending);

  // Conflict detection — both local (git index) and GitHub PR-level
  const localConflicts = repoContext?.conflict_files ?? [];
  const hasLocalConflicts = localConflicts.length > 0;
  const prHasConflicts = branchPR?.mergeable === false && branchPR.mergeable_state === "dirty";
  const hasAnyConflicts = hasLocalConflicts || prHasConflicts;

  // Preview deployments — check if any provider is configured
  const hasPreviewProvider = Object.values(previewProvidersConfigured).some(Boolean);
  const branchPreviews = previews.filter(
    (p) => p.branch === currentBranch && p.status !== "destroyed",
  );
  const hasActiveBranchPreview = branchPreviews.length > 0;
  const canDeployPreview = !!(isOnFeatureBranch && hasPreviewProvider && !hasActiveBranchPreview);

  // Do we have any visible GitHub/Deploy buttons?
  const hasGitHubActions = canMakePR || canMerge || branchPR || hasPreviewProvider || hasAnyConflicts;

  const btnBase = "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed";

  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 mb-1.5 px-0.5">
      {/* ── Agent actions ─────────────────────────────────────────── */}
      <button
        onClick={fireSuperlaser}
        disabled={!canCompact}
        className={`${btnBase} border border-border-subtle text-text-secondary hover:border-accent/30 hover:text-accent hover:bg-accent/10`}
        title="Compact conversation context"
      >
        <Archive size={12} />
        Compact
      </button>

      <button
        onClick={fetchMemorySuggestions}
        disabled={!canSuggestMemories}
        className={`${btnBase} border border-border-subtle text-text-secondary hover:border-accent/30 hover:text-accent hover:bg-accent/10`}
        title="Extract reusable memories from this conversation"
      >
        {suggestingMemories ? <Loader2 size={12} className="animate-spin" /> : <Brain size={12} />}
        Memories
      </button>

      {workflow === "review" && (
        <button
          onClick={() => { if (canStartReview) sendMessage(""); }}
          disabled={!canStartReview}
          className={`${btnBase} bg-accent text-bg-deep hover:bg-accent-hover`}
          title={!selectedPR ? "Select a PR first" : "Start code review"}
        >
          <ScanSearch size={12} />
          Start Review
        </button>
      )}

      <button
        onClick={pokeAgent}
        disabled={!canNudge}
        className={`${btnBase} border border-warning/30 text-warning hover:bg-warning/10`}
        title="Nudge the agent to continue"
      >
        <Zap size={12} />
        Nudge
      </button>

      <button
        onClick={interruptAgent}
        disabled={!canStop}
        className={`${btnBase} border border-error/30 text-error hover:bg-error/10`}
        title="Stop the agent"
      >
        <Square size={10} fill="currentColor" />
        Stop
      </button>

      {/* ── Separator between agent and GitHub/Deploy actions ───── */}
      {hasGitHubActions && (
        <div className="mx-0.5 h-5 w-px bg-border-subtle" />
      )}

      {/* ── GitHub / Deploy actions ───────────────────────────────── */}
      <button
        onClick={() => {
          if (canMakePR) {
            if (branchPR) {
              sendMessage(
                `First, commit any uncommitted changes locally with a clean commit message. Then update the PR description and title for PR #${branchPR.number} based on the latest commits and changes on this branch.`,
              );
            } else {
              sendMessage(
                "Open a pull request for the changes on this branch. Write a good PR title and description based on the commits and changes.",
              );
            }
          }
        }}
        disabled={!canMakePR}
        className={`${btnBase} border border-accent/30 text-accent hover:bg-accent/10`}
        title={!isOnFeatureBranch ? "Switch to a feature branch first" : !conversationId ? "Start a conversation first" : branchPR ? `Update PR #${branchPR.number}` : "Create a pull request"}
      >
        {branchPR ? <RefreshCw size={12} /> : <GitPullRequest size={12} />}
        {branchPR ? `Update PR #${branchPR.number}` : "Make PR"}
      </button>

      <button
        onClick={() => {
          if (canMerge && branchPR) {
            sendMessage(
              `Merge PR #${branchPR.number} on branch "${currentBranch}". Use a squash merge if possible. After merging, confirm it was successful.`,
            );
          }
        }}
        disabled={!canMerge}
        className={`${btnBase} border border-success/30 text-success hover:bg-success/10`}
        title={branchPR ? `Merge PR #${branchPR.number}` : "No open PR on this branch"}
      >
        <GitMerge size={12} />
        Merge
      </button>

      {/* Conflict indicators + actions */}
      {hasLocalConflicts && (
        <button
          onClick={() => {
            setWorkflow("patch");
            const fileList = localConflicts.map((f) => `- ${f}`).join("\n");
            sendMessage(
              `Resolve the merge conflicts in the following files. For each file, read it, understand both sides of the conflict, choose the best resolution that preserves intended functionality from both branches, remove all conflict markers, and then save the file.\n\nConflicted files:\n${fileList}\n\nAfter resolving all conflicts, run \`git add\` on each resolved file.`,
            );
          }}
          disabled={sending}
          className={`${btnBase} border border-error/30 text-error hover:bg-error/10`}
          title={`Local merge conflicts in ${localConflicts.length} file(s): ${localConflicts.join(", ")}`}
        >
          <AlertTriangle size={12} />
          Resolve {localConflicts.length} Conflict{localConflicts.length > 1 ? "s" : ""}
        </button>
      )}

      {prHasConflicts && !hasLocalConflicts && (
        <button
          onClick={() => syncBranch(branchPR?.base_branch)}
          disabled={sending}
          className={`${btnBase} border border-error/30 text-error hover:bg-error/10`}
          title={`PR #${branchPR?.number} has merge conflicts on GitHub — sync with ${branchPR?.base_branch || "main"} to resolve`}
        >
          <AlertTriangle size={12} />
          PR Conflicts
        </button>
      )}

      {hasPreviewProvider && (
        hasActiveBranchPreview ? (
          <PreviewBadge
            previews={branchPreviews}
            onTearDown={deletePreview}
            onRefresh={refreshPreview}
          />
        ) : (
          <button
            onClick={createPreview}
            disabled={!canDeployPreview}
            className={`${btnBase} border border-info/30 text-info hover:bg-info/10`}
            title={!isOnFeatureBranch ? "Switch to a feature branch first" : "Deploy a preview of this branch"}
          >
            <Globe size={12} />
            Deploy Preview
          </button>
        )
      )}

      {/* ── Right: queue + status ─────────────────────────────────── */}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {serverQueue.length > 0 && (
          <QueueBadge items={serverQueue} onCancel={cancelQueueItem} onClearAll={clearQueue} />
        )}
        {isBusy && (
          <span className="text-[10px] text-text-muted animate-pulse">
            {compacting ? "Compacting..." : "Working..."}
          </span>
        )}
      </div>

      <SuggestMemoriesDialog />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Queue badge — shows pending/processing items with per-item cancel
// ---------------------------------------------------------------------------

function QueueBadge({
  items,
  onCancel,
  onClearAll,
}: {
  items: ServerQueueItem[];
  onCancel: (id: string) => Promise<void>;
  onClearAll: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const processing = items.filter((i) => i.status === "processing");
  const pending = items.filter((i) => i.status === "pending");

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-warning hover:text-warning/80 transition-colors"
        title="View queued messages"
      >
        {processing.length > 0 && (
          <Loader2 size={10} className="animate-spin" />
        )}
        {items.length} queued
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          {/* Popover */}
          <div className="absolute bottom-full right-0 z-50 mb-2 w-72 rounded-lg border border-border-subtle bg-bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
              <span className="text-[11px] font-medium text-text-secondary">
                Message Queue
              </span>
              {pending.length > 0 && (
                <button
                  onClick={() => { onClearAll(); setOpen(false); }}
                  className="text-[10px] text-text-muted hover:text-error transition-colors"
                >
                  Clear pending
                </button>
              )}
            </div>
            <div className="max-h-52 overflow-y-auto divide-y divide-border-subtle/50">
              {items.map((item) => (
                <div key={item.id} className="flex items-start gap-2 px-3 py-2">
                  <div className="mt-0.5 shrink-0">
                    {item.status === "processing" ? (
                      <Loader2 size={10} className="animate-spin text-accent" />
                    ) : (
                      <div className="h-2 w-2 rounded-full bg-warning/60 mt-0.5" />
                    )}
                  </div>
                  <p className="flex-1 truncate text-[11px] text-text-secondary" title={item.message}>
                    {item.message}
                  </p>
                  <button
                    onClick={() => { onCancel(item.id); setOpen(false); }}
                    className="shrink-0 text-text-muted hover:text-error transition-colors"
                    title={item.status === "processing" ? "Interrupt and cancel" : "Cancel"}
                  >
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
            {processing.length > 0 && (
              <div className="border-t border-border-subtle/50 px-3 py-1.5">
                <p className="text-[10px] text-text-muted">
                  <span className="text-accent">{processing.length} running</span>
                  {pending.length > 0 && ` · ${pending.length} waiting`}
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preview badge — shows active previews with status, URL, and tear-down
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-warning/60",
  building: "bg-warning/60",
  live: "bg-success/60",
  failed: "bg-error/60",
};

function PreviewBadge({
  previews,
  onTearDown,
  onRefresh,
}: {
  previews: PreviewDeployment[];
  onTearDown: (id: string) => Promise<void>;
  onRefresh: (id: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);

  // Auto-refresh previews that are still building
  useEffect(() => {
    const building = previews.filter(
      (p) => p.status === "pending" || p.status === "building",
    );
    if (building.length === 0) return;
    const interval = setInterval(() => {
      building.forEach((p) => onRefresh(p.id));
    }, 10_000);
    return () => clearInterval(interval);
  }, [previews, onRefresh]);

  const primary = previews[0] as PreviewDeployment | undefined;
  if (!primary) return null;
  const isBuilding = primary.status === "pending" || primary.status === "building";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] font-medium text-info hover:text-info/80 transition-colors h-7 px-2.5 rounded-md border border-info/30"
        title="Preview deployment"
      >
        {isBuilding ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Globe size={12} />
        )}
        {primary.status === "live" ? "Preview" : primary.status === "building" ? "Building..." : primary.status === "pending" ? "Starting..." : "Preview"}
        {primary.status === "live" && primary.preview_url && (
          <ExternalLink size={10} />
        )}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-lg border border-border-subtle bg-bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
              <span className="text-[11px] font-medium text-text-secondary">
                Preview Deployments
              </span>
            </div>
            <div className="max-h-52 overflow-y-auto divide-y divide-border-subtle/50">
              {previews.map((p) => (
                <div key={p.id} className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className={`h-2 w-2 rounded-full shrink-0 ${STATUS_COLORS[p.status] || "bg-text-muted"}`} />
                    <span className="flex-1 text-[11px] text-text-secondary truncate">
                      {p.branch}
                    </span>
                    <span className="text-[10px] text-text-muted capitalize">
                      {p.status}
                    </span>
                    <button
                      onClick={() => { onTearDown(p.id); setOpen(false); }}
                      className="shrink-0 text-text-muted hover:text-error transition-colors"
                      title="Tear down preview"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                  {p.preview_url && p.status === "live" && (
                    <a
                      href={p.preview_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 flex items-center gap-1 text-[10px] text-info hover:text-info/80 transition-colors truncate"
                    >
                      <ExternalLink size={8} />
                      {p.preview_url}
                    </a>
                  )}
                  {p.error_message && (
                    <p className="mt-1 text-[10px] text-error truncate" title={p.error_message}>
                      {p.error_message}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

import { useState } from "react";
import { Archive, GitMerge, GitPullRequest, Loader2, RefreshCw, ScanSearch, Square, X, Zap } from "lucide-react";
import { useStore } from "../store";
import type { ServerQueueItem } from "../types";

/**
 * Contextual action bar above the input.
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

  const currentBranch = repoContext?.branch;
  const isOnFeatureBranch = currentBranch && currentBranch !== "main" && currentBranch !== "master";
  const isAgentActive = sending && !agentStream.pendingPermission;
  const isBusy = isAgentActive || compacting;

  // Check if current branch already has an open PR
  const branchPR = currentBranch
    ? pullRequests.find((pr) => pr.state === "open" && pr.head_branch === currentBranch)
    : null;

  const canCompact = !!conversationId && !sending && !compacting;
  const canMakePR = !!(workflow === "patch" && isOnFeatureBranch && conversationId && !sending);
  const canMerge = !!(branchPR && conversationId && !sending);
  const canStartReview = !!(workflow === "review" && selectedPR !== null && !sending);
  const canNudge = isAgentActive;
  const canStop = isAgentActive;

  const btnBase = "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed";

  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 mb-1.5 px-0.5">
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
        onClick={() => {
          if (canMakePR) {
            if (branchPR) {
              sendMessage(
                `Update the PR description and title for PR #${branchPR.number} based on the latest commits and changes on this branch.`,
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

      {/* Right: queue + status — ml-auto pushes to end of whatever row it lands on */}
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
                    onClick={() => onCancel(item.id)}
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

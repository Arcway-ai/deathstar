import { Archive, GitPullRequest, ScanSearch, X } from "lucide-react";
import { useStore } from "../store";

/**
 * Contextual action bar above the input.
 * Shows relevant actions based on workflow, branch, and agent state.
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
  const agentStream = useStore((s) => s.agentStream);
  const fireSuperlaser = useStore((s) => s.fireSuperlaser);
  const conversationId = useStore((s) => s.conversationId);

  const currentBranch = repoContext?.branch;
  const isOnFeatureBranch = currentBranch && currentBranch !== "main" && currentBranch !== "master";
  const isAgentActive = sending && !agentStream.pendingPermission;
  const isBusy = isAgentActive || compacting;

  const showMakePR = workflow === "patch" && isOnFeatureBranch && !sending;
  const showStartReview = workflow === "review" && selectedPR !== null && !sending;
  const showCompact = !sending && !compacting && !!conversationId;
  const showQueue = serverQueue.length > 0;

  // Nothing to show
  if (!showMakePR && !showStartReview && !showCompact && !showQueue) return null;

  return (
    <div className="flex items-center gap-1.5 mb-1.5 px-0.5">
      {/* Left: contextual actions */}
      <div className="flex items-center gap-1.5">
        {showCompact && (
          <button
            onClick={fireSuperlaser}
            className="flex h-7 items-center gap-1.5 rounded-md border border-border-subtle px-2.5 text-[11px] font-medium text-text-secondary transition-colors hover:border-accent/30 hover:text-accent hover:bg-accent/10"
            title="Compact conversation context"
          >
            <Archive size={12} />
            Compact
          </button>
        )}

        {showMakePR && (
          <button
            onClick={() => {
              sendMessage(
                "Open a pull request for the changes on this branch. Write a good PR title and description based on the commits and changes.",
              );
            }}
            className="flex h-7 items-center gap-1.5 rounded-md border border-accent/30 px-2.5 text-[11px] font-medium text-accent transition-colors hover:bg-accent/10"
          >
            <GitPullRequest size={12} />
            Make PR
          </button>
        )}

        {showStartReview && (
          <button
            onClick={() => sendMessage("")}
            className="flex h-7 items-center gap-1.5 rounded-md bg-accent px-2.5 text-[11px] font-medium text-bg-deep transition-colors hover:bg-accent-hover"
          >
            <ScanSearch size={12} />
            Start Review
          </button>
        )}
      </div>

      {/* Right: queue status */}
      <div className="ml-auto flex items-center gap-1.5">
        {showQueue && (
          <div className="flex items-center gap-1 text-[10px]">
            <span className="text-warning">
              {serverQueue.length} queued
            </span>
            <button
              onClick={clearQueue}
              className="text-text-muted hover:text-warning transition-colors"
              title="Clear queue"
            >
              <X size={10} />
            </button>
          </div>
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

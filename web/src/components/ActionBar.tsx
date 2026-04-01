import { Archive, GitPullRequest, ScanSearch, Square, X, Zap } from "lucide-react";
import { useStore } from "../store";

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
  const agentStream = useStore((s) => s.agentStream);
  const fireSuperlaser = useStore((s) => s.fireSuperlaser);
  const conversationId = useStore((s) => s.conversationId);
  const pokeAgent = useStore((s) => s.pokeAgent);
  const interruptAgent = useStore((s) => s.interruptAgent);

  const currentBranch = repoContext?.branch;
  const isOnFeatureBranch = currentBranch && currentBranch !== "main" && currentBranch !== "master";
  const isAgentActive = sending && !agentStream.pendingPermission;
  const isBusy = isAgentActive || compacting;

  const canCompact = !!conversationId && !sending && !compacting;
  const canMakePR = !!(workflow === "patch" && isOnFeatureBranch && conversationId && !sending);
  const canStartReview = !!(workflow === "review" && selectedPR !== null && !sending);
  const canNudge = isAgentActive;
  const canStop = isAgentActive;

  const btnBase = "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed";

  return (
    <div className="flex items-center gap-1.5 mb-1.5 px-0.5">
      {/* Left: actions */}
      <div className="flex items-center gap-1.5">
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
              sendMessage(
                "Open a pull request for the changes on this branch. Write a good PR title and description based on the commits and changes.",
              );
            }
          }}
          disabled={!canMakePR}
          className={`${btnBase} border border-accent/30 text-accent hover:bg-accent/10`}
          title={!isOnFeatureBranch ? "Switch to a feature branch first" : !conversationId ? "Start a conversation first" : "Create a pull request"}
        >
          <GitPullRequest size={12} />
          Make PR
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
      </div>

      {/* Right: queue + status */}
      <div className="ml-auto flex items-center gap-1.5">
        {serverQueue.length > 0 && (
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

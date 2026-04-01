import { useState, useRef, useEffect } from "react";
import { Send, AlertCircle, Square, ScanSearch, Zap, GitPullRequest } from "lucide-react";
import { useStore } from "../store";
import { SuperlaserButton } from "./Superlaser";

export default function InputBar() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sending = useStore((s) => s.sending);
  const compacting = useStore((s) => s.compacting);
  const sendError = useStore((s) => s.sendError);
  const sendMessage = useStore((s) => s.sendMessage);
  const sendAgentInput = useStore((s) => s.sendAgentInput);
  const interruptAgent = useStore((s) => s.interruptAgent);
  const pokeAgent = useStore((s) => s.pokeAgent);
  const agentStream = useStore((s) => s.agentStream);
  const repoContext = useStore((s) => s.repoContext);
  const workflow = useStore((s) => s.workflow);
  const selectedPR = useStore((s) => s.selectedPR);

  const serverQueue = useStore((s) => s.serverQueue);
  const clearQueue = useStore((s) => s.clearQueue);

  const hasPendingPermission = agentStream.pendingPermission !== null;
  const isAgentWaitingForInput = sending && !agentStream.isStreaming && !hasPendingPermission;
  const isAgentActive = sending && !hasPendingPermission;
  const isBusy = (sending && !isAgentWaitingForInput) || compacting;

  // Review mode: can start without typing if a PR is selected
  const isReviewReady = workflow === "review" && selectedPR !== null;
  const canSend = text.trim() || isReviewReady;

  // Show "Make PR" when on a non-default branch with code workflow
  const currentBranch = repoContext?.branch;
  const isOnFeatureBranch = currentBranch && currentBranch !== "main" && currentBranch !== "master";
  const showMakePR = workflow === "patch" && isOnFeatureBranch && !sending;

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleSubmit = () => {
    const trimmed = text.trim();

    // For review mode, allow empty prompt (auto-generated from PR)
    if (!trimmed && !isReviewReady) return;

    // Branch guard: warn if on main with code workflow
    if (repoContext?.branch === "main" || repoContext?.branch === "master") {
      if (workflow === "patch") {
        const confirmed = window.confirm(
          `You're on the ${repoContext.branch} branch. Switch to a feature branch before making code changes. Continue anyway?`,
        );
        if (!confirmed) return;
      }
    }

    if (isAgentWaitingForInput) {
      sendAgentInput(trimmed);
    } else {
      // sendMessage handles review prompt auto-generation when trimmed is empty
      sendMessage(trimmed);
    }
    setText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const placeholder = isAgentWaitingForInput
    ? "Claude is waiting for your response..."
    : isBusy
      ? "Type a message to queue for when the agent finishes…"
      : isReviewReady
        ? "Optional: add focus areas or just hit Start Review…"
        : "Ask about this codebase…";

  return (
    <div>
      {sendError && (
        <div className="mb-2 flex items-center gap-1.5 rounded-md bg-error/10 px-3 py-1.5 text-xs text-error">
          <AlertCircle size={12} />
          {sendError}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-border-subtle bg-bg-surface p-2 focus-within:border-accent/50 transition-colors">
        <SuperlaserButton />
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-text-primary placeholder:text-text-muted outline-none"
        />
        {isAgentActive ? (
          <>
            <button
              onClick={pokeAgent}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-warning/40 text-warning transition-colors hover:bg-warning/10"
              title="Poke — nudge the agent to continue"
            >
              <Zap size={14} />
            </button>
            <button
              onClick={interruptAgent}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-error/80 text-white transition-opacity hover:bg-error"
              title="Stop agent"
            >
              <Square size={12} fill="currentColor" />
            </button>
          </>
        ) : showMakePR ? (
          <>
            <button
              onClick={() => {
                const msg = text.trim()
                  ? `Open a pull request for the changes on this branch. Additional context: ${text.trim()}`
                  : "Open a pull request for the changes on this branch. Write a good PR title and description based on the commits and changes.";
                sendMessage(msg);
                setText("");
              }}
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-accent/40 text-accent px-3 transition-colors hover:bg-accent/10 text-xs font-medium"
              title="Commit, push, and open a pull request"
            >
              <GitPullRequest size={14} />
              Make PR
            </button>
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-bg-deep transition-opacity disabled:opacity-30 hover:bg-accent-hover"
            >
              <Send size={14} />
            </button>
          </>
        ) : isReviewReady && !text.trim() ? (
          <button
            onClick={handleSubmit}
            disabled={!canSend}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-accent text-bg-deep px-3 transition-opacity disabled:opacity-30 hover:bg-accent-hover text-xs font-medium"
          >
            <ScanSearch size={14} />
            Start Review
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!canSend}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-bg-deep transition-opacity disabled:opacity-30 hover:bg-accent-hover"
          >
            <Send size={14} />
          </button>
        )}
      </div>
      <div className="mt-1 hidden sm:flex items-center justify-center gap-2">
        <p className="text-[10px] text-text-muted">
          Shift+Enter for new line · Enter to {isBusy ? "queue" : "send"}
          {isAgentActive && " · Esc to stop"}
        </p>
        {serverQueue.length > 0 && (
          <button
            onClick={clearQueue}
            className="text-[10px] text-warning hover:text-warning/80 transition-colors"
          >
            {serverQueue.length} queued · clear
          </button>
        )}
      </div>
    </div>
  );
}

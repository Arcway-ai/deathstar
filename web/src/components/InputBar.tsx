import { useState, useRef, useEffect } from "react";
import { Send, AlertCircle, Square, ScanSearch, Zap } from "lucide-react";
import { useStore } from "../store";
import { SuperlaserButton } from "./Superlaser";

export default function InputBar() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sending = useStore((s) => s.sending);
  const sendError = useStore((s) => s.sendError);
  const sendMessage = useStore((s) => s.sendMessage);
  const sendAgentInput = useStore((s) => s.sendAgentInput);
  const interruptAgent = useStore((s) => s.interruptAgent);
  const pokeAgent = useStore((s) => s.pokeAgent);
  const agentStream = useStore((s) => s.agentStream);
  const repoContext = useStore((s) => s.repoContext);
  const workflow = useStore((s) => s.workflow);
  const selectedPR = useStore((s) => s.selectedPR);

  const hasPendingPermission = agentStream.pendingPermission !== null;
  const isAgentWaitingForInput = sending && !agentStream.isStreaming && !hasPendingPermission;
  const isAgentActive = sending && !hasPendingPermission;

  // Review mode: can start without typing if a PR is selected
  const isReviewReady = workflow === "review" && selectedPR !== null;
  const canSend = text.trim() || isReviewReady;

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleSubmit = () => {
    if (sending && !isAgentWaitingForInput) return;
    const trimmed = text.trim();

    // For review mode, allow empty prompt (auto-generated from PR)
    if (!trimmed && !isReviewReady) return;

    // Branch guard: warn if on main
    if (repoContext?.branch === "main" || repoContext?.branch === "master") {
      const { openPR } = useStore.getState();
      if (workflow === "patch") {
        const action = openPR ? "open a PR" : "apply code changes";
        const confirmed = window.confirm(
          `You're on the ${repoContext.branch} branch. Switch to a feature branch before you ${action}. Continue anyway?`,
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
          disabled={sending && !isAgentWaitingForInput}
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
        ) : isReviewReady && !text.trim() ? (
          <button
            onClick={handleSubmit}
            disabled={sending && !isAgentWaitingForInput}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-accent text-bg-deep px-3 transition-opacity disabled:opacity-30 hover:bg-accent-hover text-xs font-medium"
          >
            <ScanSearch size={14} />
            Start Review
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!canSend || (sending && !isAgentWaitingForInput)}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-bg-deep transition-opacity disabled:opacity-30 hover:bg-accent-hover"
          >
            <Send size={14} />
          </button>
        )}
      </div>
      <p className="mt-1 text-center text-[10px] text-text-muted">
        Shift+Enter for new line · Enter to send
        {isAgentActive && " · Esc to stop"}
      </p>
    </div>
  );
}

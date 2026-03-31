import { useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { ThinkingDeathStar, DeathStarSpinner } from "./DeathStarLoader";
import MessageBubble from "./MessageBubble";
import AgentStreamView from "./AgentStreamView";
import InputBar from "./InputBar";
import WorkflowPills from "./WorkflowPills";
import Starfield from "./Starfield";
import { ArrowDown, AlertTriangle, GitMerge } from "lucide-react";

export default function ChatView() {
  const activeConversation = useStore((s) => s.activeConversation);
  const sending = useStore((s) => s.sending);
  const agentStream = useStore((s) => s.agentStream);
  const streamingProgress = useStore((s) => s.streamingProgress);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const persona = useStore((s) => s.persona);
  const repoContext = useStore((s) => s.repoContext);
  const sendMessage = useStore((s) => s.sendMessage);
  const setWorkflow = useStore((s) => s.setWorkflow);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);

  const conflictFiles = repoContext?.conflict_files ?? [];

  const messages = activeConversation?.messages ?? [];
  const hasAgentBlocks = agentStream.blocks.length > 0;
  const isWaiting = sending && !hasAgentBlocks;

  const NEAR_BOTTOM_THRESHOLD = 150;

  const checkIfNearBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_THRESHOLD;
    setIsNearBottom(nearBottom);
  }, []);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsNearBottom(true);
    }
  }, []);

  // Auto-scroll only when already near the bottom
  useEffect(() => {
    if (isNearBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, sending, agentStream.blocks.length, isNearBottom]);

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <Starfield />
      {/* Messages area */}
      <div
        ref={scrollRef}
        onScroll={checkIfNearBottom}
        className="relative z-10 flex-1 overflow-y-auto px-4 py-4 scroll-smooth"
      >
        {messages.length === 0 && !sending ? (
          <EmptyState repo={selectedRepo!} personaName={persona.shortName} />
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={msg.id} message={msg} index={i} />
            ))}
            {hasAgentBlocks && (
              <div className="animate-fade-in">
                <AgentStreamView blocks={agentStream.blocks} />
                {streamingProgress && (
                  <p className="mt-2 text-xs text-text-muted animate-pulse">
                    {streamingProgress}
                  </p>
                )}
              </div>
            )}
            {isWaiting && (
              <div>
                {streamingProgress && (
                  <p className="mb-2 text-xs text-text-muted animate-pulse">
                    {streamingProgress}
                  </p>
                )}
                <ThinkingDeathStar />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Conflict banner */}
      {conflictFiles.length > 0 && (
        <div className="border-t border-error/30 bg-error/5 px-4 py-2">
          <div className="mx-auto flex max-w-3xl items-start gap-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-error" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-error">
                Merge conflicts in {conflictFiles.length} file{conflictFiles.length > 1 ? "s" : ""}
              </p>
              <p className="mt-0.5 text-[11px] text-text-muted truncate">
                {conflictFiles.join(", ")}
              </p>
            </div>
            <button
              onClick={() => {
                setWorkflow("patch");
                const fileList = conflictFiles.map((f) => `- ${f}`).join("\n");
                sendMessage(
                  `Resolve the merge conflicts in the following files. For each file, read it, understand both sides of the conflict, choose the best resolution that preserves intended functionality from both branches, remove all conflict markers, and then save the file.\n\nConflicted files:\n${fileList}\n\nAfter resolving all conflicts, run \`git add\` on each resolved file.`,
                );
              }}
              disabled={sending}
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-error/20 px-3 py-1.5 text-xs font-medium text-error hover:bg-error/30 transition-colors disabled:opacity-50"
            >
              <GitMerge size={12} />
              Resolve Conflicts
            </button>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-border-subtle bg-bg-primary px-4 pb-4 pt-2">
        <div className="mx-auto max-w-3xl">
          {!isNearBottom && sending && (
            <div className="flex justify-end mb-1.5">
              <button
                onClick={scrollToBottom}
                className="flex items-center gap-1.5 rounded-full border border-border-subtle bg-bg-surface/95 px-3 py-1.5 text-xs font-medium text-text-secondary shadow-lg backdrop-blur transition-colors hover:bg-bg-surface hover:text-text-primary"
              >
                <ArrowDown size={12} />
                Jump to latest
              </button>
            </div>
          )}
          <WorkflowPills />
          <InputBar />
        </div>
      </div>
    </div>
  );
}

function EmptyState({ repo, personaName }: { repo: string; personaName: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <DeathStarSpinner size={64} className="mx-auto mb-4" />
        <h2 className="font-display text-2xl font-bold text-text-primary mb-2">
          {repo}
        </h2>
        <p className="text-sm text-text-muted max-w-md">
          Active persona: <span className="text-text-secondary">{personaName}</span>.
          <br />
          Ask anything about this codebase — chat, generate patches, or request reviews.
        </p>
      </div>
    </div>
  );
}

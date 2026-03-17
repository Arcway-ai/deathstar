import { useEffect, useRef } from "react";
import { useStore } from "../store";
import MessageBubble from "./MessageBubble";
import InputBar from "./InputBar";
import WorkflowPills from "./WorkflowPills";

export default function ChatView() {
  const activeConversation = useStore((s) => s.activeConversation);
  const sending = useStore((s) => s.sending);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const persona = useStore((s) => s.persona);
  const scrollRef = useRef<HTMLDivElement>(null);

  const messages = activeConversation?.messages ?? [];

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, sending]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 scroll-smooth"
      >
        {messages.length === 0 ? (
          <EmptyState repo={selectedRepo!} personaName={persona.shortName} />
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={msg.id} message={msg} index={i} />
            ))}
            {sending && <ThinkingIndicator />}
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-border-subtle bg-bg-primary px-4 pb-4 pt-2">
        <div className="mx-auto max-w-3xl">
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

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-3 px-4 animate-fade-in">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-accent"
          style={{
            animation: "pulse-dot 1.4s ease-in-out infinite",
            animationDelay: `${i * 0.16}s`,
          }}
        />
      ))}
      <span className="ml-2 text-xs text-text-muted">Thinking…</span>
    </div>
  );
}

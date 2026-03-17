import { useState, useRef, useEffect } from "react";
import { Send, AlertCircle } from "lucide-react";
import { useStore } from "../store";

export default function InputBar() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sending = useStore((s) => s.sending);
  const sendError = useStore((s) => s.sendError);
  const sendMessage = useStore((s) => s.sendMessage);
  const repoContext = useStore((s) => s.repoContext);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    // Branch guard: warn if on main
    if (repoContext?.branch === "main" || repoContext?.branch === "master") {
      const workflow = useStore.getState().workflow;
      if (workflow === "patch" || workflow === "pr") {
        const confirmed = window.confirm(
          `You're on the ${repoContext.branch} branch. Patch/PR workflows should use a feature branch. Continue anyway?`,
        );
        if (!confirmed) return;
      }
    }

    sendMessage(trimmed);
    setText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div>
      {sendError && (
        <div className="mb-2 flex items-center gap-1.5 rounded-md bg-error/10 px-3 py-1.5 text-xs text-error">
          <AlertCircle size={12} />
          {sendError}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-border-subtle bg-bg-surface p-2 focus-within:border-accent/50 transition-colors">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about this codebase…"
          rows={1}
          disabled={sending}
          className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-text-primary placeholder:text-text-muted outline-none"
        />
        <button
          onClick={handleSubmit}
          disabled={!text.trim() || sending}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-bg-deep transition-opacity disabled:opacity-30 hover:bg-accent-hover"
        >
          <Send size={14} />
        </button>
      </div>
      <p className="mt-1 text-center text-[10px] text-text-muted">
        Shift+Enter for new line · Enter to send
      </p>
    </div>
  );
}

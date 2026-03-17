import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  Clock,
  Cpu,
} from "lucide-react";
import { useStore } from "../store";
import type { ConversationMessage } from "../types";

export default function MessageBubble({
  message,
  index,
}: {
  message: ConversationMessage;
  index: number;
}) {
  const isUser = message.role === "user";

  return (
    <div
      className="animate-fade-in"
      style={{ animationDelay: `${Math.min(index * 0.05, 0.3)}s` }}
    >
      {isUser ? (
        <UserMessage message={message} />
      ) : (
        <AssistantMessage message={message} />
      )}
    </div>
  );
}

function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 px-4 py-2.5 text-sm text-text-primary">
        <p className="whitespace-pre-wrap">{message.content}</p>
      </div>
    </div>
  );
}

function AssistantMessage({ message }: { message: ConversationMessage }) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const thumbsUp = useStore((s) => s.thumbsUp);
  const activeConversation = useStore((s) => s.activeConversation);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleThumbsUp = async () => {
    // Find the preceding user message as the "prompt"
    const msgs = activeConversation?.messages ?? [];
    const idx = msgs.findIndex((m) => m.id === message.id);
    const prompt = idx > 0 ? msgs[idx - 1]!.content : "";
    await thumbsUp(message.id, message.content, prompt);
    setSaved(true);
  };

  return (
    <div className="group">
      <div className="prose max-w-none text-sm text-text-primary">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
          components={{
            // Wrap code blocks with copy button
            pre({ children, ...props }) {
              return (
                <div className="relative">
                  <pre {...props}>{children}</pre>
                  <button
                    onClick={handleCopy}
                    className="absolute right-2 top-2 rounded bg-bg-elevated p-1 text-text-muted opacity-0 transition-opacity hover:text-text-secondary group-hover:opacity-100"
                  >
                    {copied ? <Check size={12} /> : <Copy size={12} />}
                  </button>
                </div>
              );
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>

      {/* Metadata + actions */}
      <div className="mt-1.5 flex items-center gap-3 text-[10px] text-text-muted">
        {message.model && (
          <span className="flex items-center gap-1">
            <Cpu size={10} />
            {message.model}
          </span>
        )}
        {message.duration_ms != null && (
          <span className="flex items-center gap-1">
            <Clock size={10} />
            {(message.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
        {message.workflow && (
          <span className="rounded bg-bg-surface px-1.5 py-0.5">
            {message.workflow}
          </span>
        )}

        {/* Actions — visible on hover */}
        <div className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            onClick={handleCopy}
            className="rounded p-1 hover:bg-bg-hover"
            title="Copy response"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button
            onClick={handleThumbsUp}
            disabled={saved}
            className={`rounded p-1 hover:bg-bg-hover ${saved ? "text-success" : ""}`}
            title="Save to memory bank"
          >
            <ThumbsUp size={12} />
          </button>
          <button
            className="rounded p-1 hover:bg-bg-hover"
            title="Bad response"
          >
            <ThumbsDown size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

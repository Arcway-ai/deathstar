import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  Copy,
  Check,
  ThumbsUp,
  Clock,
  Cpu,
  Coins,
  Hash,
} from "lucide-react";
import { useStore } from "../store";
import { estimateCost, formatCost } from "../models";
import type { AgentContentBlock, ConversationMessage, ProviderName, StructuredPlan, StructuredReview } from "../types";
import PlanPanel from "./PlanPanel";
import ReviewPanel from "./ReviewPanel";
import AgentBlocksView from "./AgentBlocksView";

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

function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in (node as unknown as Record<string, unknown>)) {
    const el = node as React.ReactElement<{ children?: React.ReactNode }>;
    return extractText(el.props.children);
  }
  return "";
}

function CodeBlockCopyButton({ preChildren }: { preChildren: React.ReactNode }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const text = extractText(preChildren);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 rounded bg-bg-elevated p-1 text-text-muted opacity-0 transition-opacity hover:text-text-secondary group-hover:opacity-100"
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </button>
  );
}

/** Strip optional markdown code fences and parse JSON. */
function tryParseJSON(content: string): unknown | null {
  try {
    let raw = content.trim();
    if (raw.startsWith("```")) {
      const firstNewline = raw.indexOf("\n");
      raw = raw.slice(firstNewline + 1);
      if (raw.endsWith("```")) raw = raw.slice(0, -3).trim();
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function tryParseReview(content: string): StructuredReview | null {
  const parsed = tryParseJSON(content);
  if (
    parsed &&
    typeof parsed === "object" &&
    "summary" in parsed &&
    "verdict" in parsed &&
    "findings" in parsed &&
    Array.isArray((parsed as StructuredReview).findings)
  ) {
    return parsed as StructuredReview;
  }
  return null;
}

function tryParsePlan(content: string): StructuredPlan | null {
  const parsed = tryParseJSON(content);
  if (
    parsed &&
    typeof parsed === "object" &&
    "title" in parsed &&
    "phases" in parsed &&
    Array.isArray((parsed as StructuredPlan).phases)
  ) {
    return parsed as StructuredPlan;
  }
  return null;
}

function AssistantMessage({ message }: { message: ConversationMessage }) {
  const [copied, setCopied] = useState(false);
  const thumbsUp = useStore((s) => s.thumbsUp);
  const memoryDistillingId = useStore((s) => s.memoryDistillingId);
  const isDistilling = memoryDistillingId === message.id;
  const messageFeedback = useStore((s) => s.messageFeedback);
  const setActiveReview = useStore((s) => s.setActiveReview);
  const activeConversation = useStore((s) => s.activeConversation);
  const feedback = messageFeedback[message.id];

  const structuredReview = useMemo(() => {
    if (message.workflow !== "review" && message.workflow !== "audit") return null;
    const review = tryParseReview(message.content);
    if (review) {
      setActiveReview(review);
    }
    return review;
  }, [message.content, message.workflow, setActiveReview]);

  const structuredPlan = useMemo(() => {
    if (message.workflow !== "plan") return null;
    return tryParsePlan(message.content);
  }, [message.content, message.workflow]);

  const copyToClipboard = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      // Fallback for non-HTTPS contexts (e.g. Tailscale HTTP)
      const ta = document.createElement("textarea");
      ta.value = content;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCopy = () => copyToClipboard(message.content);

  const getPrecedingPrompt = () => {
    const msgs = activeConversation?.messages ?? [];
    const idx = msgs.findIndex((m) => m.id === message.id);
    return idx > 0 ? msgs[idx - 1]!.content : "";
  };

  const handleThumbsUp = async () => {
    await thumbsUp(message.id, message.content, getPrecedingPrompt());
  };

  // Filter out text blocks from agent_blocks — the text is already in message.content
  const nonTextBlocks = useMemo(() => {
    if (!message.agent_blocks) return null;
    const filtered = message.agent_blocks.filter((b: AgentContentBlock) => b.type !== "text");
    return filtered.length > 0 ? filtered : null;
  }, [message.agent_blocks]);

  return (
    <div className="group border-l-2 border-accent/20 pl-3">
      {/* Agent tool history (thinking, tool calls, results) */}
      {nonTextBlocks && <AgentBlocksView blocks={nonTextBlocks} />}

      {structuredReview ? (
        <ReviewPanel review={structuredReview} />
      ) : structuredPlan ? (
        <PlanPanel plan={structuredPlan} />
      ) : (
        <div className="prose max-w-none text-sm text-text-primary">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{
              // Open links in a new tab
              a({ children, ...props }) {
                return (
                  <a {...props} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                );
              },
              // Wrap code blocks with copy button
              pre({ children, ...props }) {
                return (
                  <div className="relative">
                    <pre {...props}>{children}</pre>
                    <CodeBlockCopyButton preChildren={children} />
                  </div>
                );
              },
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>
      )}

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
        {message.usage?.total_tokens != null && (
          <span className="flex items-center gap-1" title={`${message.usage.input_tokens?.toLocaleString() ?? "?"} in / ${message.usage.output_tokens?.toLocaleString() ?? "?"} out`}>
            <Hash size={10} />
            {message.usage.total_tokens.toLocaleString()}
          </span>
        )}
        {message.provider && message.model && message.usage && (() => {
          const cost = estimateCost(
            message.provider as ProviderName,
            message.model,
            message.usage.input_tokens,
            message.usage.output_tokens,
          );
          return cost != null ? (
            <span className="flex items-center gap-1" title={`Estimated cost: ${formatCost(cost)}`}>
              <Coins size={10} />
              {formatCost(cost)}
            </span>
          ) : null;
        })()}
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
            disabled={!!feedback || isDistilling}
            className={`rounded p-1 hover:bg-bg-hover ${feedback === "thumbs_up" ? "text-success" : ""} ${isDistilling ? "animate-pulse" : ""}`}
            title={isDistilling ? "Extracting memories..." : "Extract memories from this response"}
          >
            <ThumbsUp size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Search,
  Terminal,
  PenLine,
  Brain,
  ShieldQuestion,
  Check,
  X,
  AlertTriangle,
} from "lucide-react";
import { useStore } from "../store";
import type { AgentContentBlock } from "../types";
import LightsaberIndicator from "./LightsaberIndicator";

const TOOL_ICONS: Record<string, typeof FileText> = {
  Read: FileText,
  Write: PenLine,
  Edit: PenLine,
  Glob: Search,
  Grep: Search,
  Bash: Terminal,
  WebSearch: Search,
  WebFetch: Search,
};

export default function AgentStreamView({
  blocks,
}: {
  blocks: AgentContentBlock[];
}) {
  const startedAt = useStore((s) => s.agentStream.startedAt);
  const statusMessage = useStore((s) => s.agentStream.statusMessage);

  return (
    <div className="min-w-0 space-y-2 overflow-hidden">
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
      {/* Status banner (e.g. rate limited) */}
      {statusMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2">
          <AlertTriangle size={12} className="shrink-0 text-warning" />
          <span className="text-xs text-warning">{statusMessage}</span>
        </div>
      )}
      {/* Lightsaber + elapsed timer */}
      <div className="flex items-center gap-2">
        <LightsaberIndicator className="ml-0.5" />
        {startedAt && <ElapsedTimer startedAt={startedAt} />}
      </div>
    </div>
  );
}

function BlockView({ block }: { block: AgentContentBlock }) {
  switch (block.type) {
    case "text":
      return <TextBlockView text={block.text} />;
    case "thinking":
      return <ThinkingBlockView text={block.text} />;
    case "tool_use":
      return <ToolUseBlockView tool={block.tool} input={block.input} />;
    case "tool_result":
      return (
        <ToolResultBlockView
          content={block.content}
          isError={block.isError}
        />
      );
    case "permission_request":
      return <PermissionRequestView tool={block.tool} input={block.input} />;
    default:
      return null;
  }
}

function TextBlockView({ text }: { text: string }) {
  return (
    <div className="prose min-w-0 max-w-none overflow-hidden text-sm text-text-primary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a({ children, ...props }) {
            return (
              <a {...props} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ThinkingBlockView({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-border-subtle/50 bg-bg-surface/50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors"
      >
        <Brain size={12} className="text-purple-400" />
        <span className="font-medium">Thinking</span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="border-t border-border-subtle/50 px-3 py-2 text-xs text-text-muted leading-relaxed whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}

function ToolUseBlockView({
  tool,
  input,
}: {
  tool: string;
  input: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  const Icon = TOOL_ICONS[tool] ?? Terminal;

  // Build a short summary from the input
  const summary = _toolSummary(tool, input);

  return (
    <div className="rounded-lg border border-accent/20 bg-accent/5">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
      >
        <Icon size={12} className="text-accent" />
        <span className="font-mono font-medium">{tool}</span>
        {summary && (
          <span className="truncate text-text-muted">{summary}</span>
        )}
        <div className="flex-1" />
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="border-t border-accent/10 px-3 py-2">
          <pre className="text-[11px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(input, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function ToolResultBlockView({
  content,
  isError,
}: {
  content: string;
  isError: boolean;
}) {
  const [open, setOpen] = useState(false);
  const isLong = content.length > 200;
  const preview = isLong ? content.slice(0, 200) + "..." : content;

  return (
    <div
      className={`rounded-lg border ${
        isError ? "border-error/30 bg-error/5" : "border-border-subtle/50 bg-bg-surface/30"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors"
      >
        {isError ? (
          <AlertTriangle size={12} className="text-error" />
        ) : (
          <Check size={12} className="text-success" />
        )}
        <span className="font-medium">{isError ? "Error" : "Result"}</span>
        {!open && isLong && (
          <span className="truncate text-text-muted/70">{preview.slice(0, 60)}</span>
        )}
        <div className="flex-1" />
        {isLong && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
      </button>
      {(open || !isLong) && (
        <div className="border-t border-border-subtle/30 px-3 py-2">
          <pre className="text-[11px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
            {open ? content : preview}
          </pre>
        </div>
      )}
    </div>
  );
}

function PermissionRequestView({
  tool,
  input,
}: {
  tool: string;
  input: Record<string, unknown>;
}) {
  const respondToPermission = useStore((s) => s.respondToPermission);
  const pendingPermission = useStore((s) => s.agentStream.pendingPermission);
  const isActive = pendingPermission?.tool === tool;

  const summary = _toolSummary(tool, input);

  return (
    <div className="rounded-lg border-2 border-warning/50 bg-warning/10 p-3">
      <div className="flex items-center gap-2 mb-2">
        <ShieldQuestion size={16} className="text-warning" />
        <span className="text-sm font-medium text-text-primary">
          Permission Required
        </span>
      </div>
      <p className="text-xs text-text-secondary mb-2">
        Claude wants to use <span className="font-mono font-medium text-text-primary">{tool}</span>
        {summary && <span className="text-text-muted"> — {summary}</span>}
      </p>
      <pre className="text-[11px] text-text-muted bg-bg-deep/50 rounded px-2 py-1.5 mb-3 overflow-x-auto whitespace-pre-wrap max-h-32 overflow-y-auto">
        {JSON.stringify(input, null, 2)}
      </pre>
      {isActive && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => respondToPermission(true)}
            className="flex items-center gap-1.5 rounded-lg bg-success/20 px-4 py-2 text-sm sm:px-3 sm:py-1.5 sm:text-xs font-medium text-success hover:bg-success/30 active:bg-success/40 transition-colors"
          >
            <Check size={14} className="sm:size-3" />
            Allow
          </button>
          <button
            onClick={() => respondToPermission(false)}
            className="flex items-center gap-1.5 rounded-lg bg-error/20 px-4 py-2 text-sm sm:px-3 sm:py-1.5 sm:text-xs font-medium text-error hover:bg-error/30 active:bg-error/40 transition-colors"
          >
            <X size={14} className="sm:size-3" />
            Deny
          </button>
        </div>
      )}
    </div>
  );
}

function ElapsedTimer({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const display = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  return (
    <span className="text-[11px] font-mono text-text-muted tabular-nums">
      {display}
    </span>
  );
}

/** Build a short human-readable summary for a tool call. */
function _toolSummary(tool: string, input: Record<string, unknown>): string {
  switch (tool) {
    case "Read":
      return String(input.file_path ?? input.path ?? "");
    case "Write":
      return String(input.file_path ?? input.path ?? "");
    case "Edit":
      return String(input.file_path ?? input.path ?? "");
    case "Glob":
      return String(input.pattern ?? "");
    case "Grep":
      return String(input.pattern ?? "");
    case "Bash":
      return String(input.command ?? "").slice(0, 80);
    case "WebSearch":
      return String(input.query ?? "");
    default:
      return "";
  }
}

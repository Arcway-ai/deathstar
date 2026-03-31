import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Search,
  Terminal,
  PenLine,
  Brain,
  Check,
  AlertTriangle,
  Activity,
} from "lucide-react";
import type { AgentContentBlock } from "../types";

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

/**
 * Renders saved agent blocks (thinking, tool_use, tool_result) for historical messages.
 * All blocks are collapsed by default since this is history, not live streaming.
 */
export default function AgentBlocksView({ blocks }: { blocks: AgentContentBlock[] }) {
  const [expanded, setExpanded] = useState(false);

  const count = blocks.length;
  const thinkingCount = blocks.filter((b) => b.type === "thinking").length;
  const toolCount = blocks.filter((b) => b.type === "tool_use").length;

  const parts: string[] = [];
  if (thinkingCount > 0) parts.push(`${thinkingCount} thinking`);
  if (toolCount > 0) parts.push(`${toolCount} tool call${toolCount > 1 ? "s" : ""}`);
  const summary = parts.join(", ") || `${count} block${count > 1 ? "s" : ""}`;

  return (
    <div className="mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/5 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-accent/10 transition-colors"
      >
        <Activity size={13} className="text-accent shrink-0" />
        <span className="font-medium">Agent trace</span>
        <span className="text-text-muted text-[11px]">{summary}</span>
        <div className="flex-1" />
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-accent/20">
          {blocks.map((block, i) => (
            <HistoryBlock key={i} block={block} />
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryBlock({ block }: { block: AgentContentBlock }) {
  switch (block.type) {
    case "thinking":
      return <ThinkingBlock text={block.text} />;
    case "tool_use":
      return <ToolUseBlock tool={block.tool} input={block.input} />;
    case "tool_result":
      return <ToolResultBlock content={block.content} isError={block.isError} />;
    default:
      return null;
  }
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const preview = text.length > 80 ? text.slice(0, 80) + "..." : text;

  return (
    <div className="rounded-md border border-border-subtle/30 bg-bg-surface/30">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1 text-[11px] text-text-muted hover:text-text-secondary transition-colors"
      >
        <Brain size={11} className="text-purple-400 shrink-0" />
        <span className="font-medium shrink-0">Thinking</span>
        {!open && <span className="truncate text-text-muted/60">{preview}</span>}
        <div className="flex-1" />
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
      </button>
      {open && (
        <div className="border-t border-border-subtle/30 px-2.5 py-1.5 text-[11px] text-text-muted leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  );
}

function ToolUseBlock({ tool, input }: { tool: string; input: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const Icon = TOOL_ICONS[tool] ?? Terminal;
  const summary = toolSummary(tool, input);

  return (
    <div className="rounded-md border border-accent/15 bg-accent/5">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1 text-[11px] text-text-secondary hover:text-text-primary transition-colors"
      >
        <Icon size={11} className="text-accent shrink-0" />
        <span className="font-mono font-medium shrink-0">{tool}</span>
        {summary && <span className="truncate text-text-muted">{summary}</span>}
        <div className="flex-1" />
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
      </button>
      {open && (
        <div className="border-t border-accent/10 px-2.5 py-1.5">
          <pre className="text-[10px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(input, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function ToolResultBlock({ content, isError }: { content: string; isError: boolean }) {
  const [open, setOpen] = useState(false);
  const isLong = content.length > 120;

  return (
    <div className={`rounded-md border ${isError ? "border-error/20 bg-error/5" : "border-border-subtle/30 bg-bg-surface/20"}`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1 text-[11px] text-text-muted hover:text-text-secondary transition-colors"
      >
        {isError ? (
          <AlertTriangle size={11} className="text-error shrink-0" />
        ) : (
          <Check size={11} className="text-success shrink-0" />
        )}
        <span className="font-medium shrink-0">{isError ? "Error" : "Result"}</span>
        {!open && <span className="truncate text-text-muted/60">{content.slice(0, 60)}</span>}
        <div className="flex-1" />
        {isLong && (open ? <ChevronDown size={10} /> : <ChevronRight size={10} />)}
      </button>
      {(open || !isLong) && (
        <div className="border-t border-border-subtle/20 px-2.5 py-1.5">
          <pre className="text-[10px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">
            {open ? content : content.slice(0, 120)}
          </pre>
        </div>
      )}
    </div>
  );
}

function toolSummary(tool: string, input: Record<string, unknown>): string {
  switch (tool) {
    case "Read":
    case "Write":
    case "Edit":
      return String(input.file_path ?? input.path ?? "");
    case "Glob":
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

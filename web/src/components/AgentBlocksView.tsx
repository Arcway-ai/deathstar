import {
  FileText,
  Search,
  Terminal,
  PenLine,
  Brain,
  Check,
  AlertTriangle,
  Activity,
} from "lucide-react";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
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
  const count = blocks.length;
  const thinkingCount = blocks.filter((b) => b.type === "thinking").length;
  const toolCount = blocks.filter((b) => b.type === "tool_use").length;

  const parts: string[] = [];
  if (thinkingCount > 0) parts.push(`${thinkingCount} thinking`);
  if (toolCount > 0) parts.push(`${toolCount} tool call${toolCount > 1 ? "s" : ""}`);
  const summary = parts.join(", ") || `${count} block${count > 1 ? "s" : ""}`;

  return (
    <div className="mb-2">
      <Accordion>
        <AccordionItem value="trace" className="rounded-lg border border-accent/20 bg-accent/5">
          <AccordionTrigger className="px-3 py-1.5 text-xs hover:no-underline hover:bg-accent/10 [&_[data-slot=accordion-trigger-icon]]:text-text-secondary [&_[data-slot=accordion-trigger-icon]]:size-3">
            <div className="flex items-center gap-2 flex-1 min-w-0 mr-2">
              <Activity size={13} className="text-accent shrink-0" />
              <span className="font-medium text-text-secondary">Agent trace</span>
              <span className="text-text-muted text-[11px]">{summary}</span>
            </div>
          </AccordionTrigger>
          <AccordionContent>
            <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-accent/20 mx-3 mb-2">
              <Accordion>
                {blocks.map((block, i) => (
                  <HistoryBlock key={i} block={block} index={i} />
                ))}
              </Accordion>
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

function HistoryBlock({ block, index }: { block: AgentContentBlock; index: number }) {
  switch (block.type) {
    case "thinking":
      return <ThinkingBlock text={block.text} index={index} />;
    case "tool_use":
      return <ToolUseBlock tool={block.tool} input={block.input} index={index} />;
    case "tool_result":
      return <ToolResultBlock content={block.content} isError={block.isError} index={index} />;
    default:
      return null;
  }
}

function ThinkingBlock({ text, index }: { text: string; index: number }) {
  const preview = text.length > 80 ? text.slice(0, 80) + "..." : text;

  return (
    <AccordionItem value={`block-${index}`} className="rounded-md border border-border-subtle/30 bg-bg-surface/30 mb-1.5">
      <AccordionTrigger className="px-2.5 py-1 text-[11px] hover:no-underline hover:text-text-secondary [&_[data-slot=accordion-trigger-icon]]:size-2.5 [&_[data-slot=accordion-trigger-icon]]:text-text-muted">
        <div className="flex items-center gap-2 flex-1 min-w-0 mr-1">
          <Brain size={11} className="text-purple-400 shrink-0" />
          <span className="font-medium text-text-muted shrink-0">Thinking</span>
          <span className="truncate text-text-muted/60 group-aria-expanded/accordion-trigger:hidden">{preview}</span>
        </div>
      </AccordionTrigger>
      <AccordionContent>
        <div className="border-t border-border-subtle/30 px-2.5 py-1.5 text-[11px] text-text-muted leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
          {text}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

function ToolUseBlock({ tool, input, index }: { tool: string; input: Record<string, unknown>; index: number }) {
  const Icon = TOOL_ICONS[tool] ?? Terminal;
  const summary = toolSummary(tool, input);

  return (
    <AccordionItem value={`block-${index}`} className="rounded-md border border-accent/15 bg-accent/5 mb-1.5">
      <AccordionTrigger className="px-2.5 py-1 text-[11px] hover:no-underline hover:text-text-primary [&_[data-slot=accordion-trigger-icon]]:size-2.5 [&_[data-slot=accordion-trigger-icon]]:text-text-muted">
        <div className="flex items-center gap-2 flex-1 min-w-0 mr-1">
          <Icon size={11} className="text-accent shrink-0" />
          <span className="font-mono font-medium text-text-secondary shrink-0">{tool}</span>
          {summary && <span className="truncate text-text-muted">{summary}</span>}
        </div>
      </AccordionTrigger>
      <AccordionContent>
        <div className="border-t border-accent/10 px-2.5 py-1.5">
          <pre className="text-[10px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(input, null, 2)}
          </pre>
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

function ToolResultBlock({ content, isError, index }: { content: string; isError: boolean; index: number }) {
  const isLong = content.length > 120;

  if (!isLong) {
    // Short results shown inline, no accordion needed
    return (
      <div className={`rounded-md border mb-1.5 ${isError ? "border-error/20 bg-error/5" : "border-border-subtle/30 bg-bg-surface/20"}`}>
        <div className="flex items-center gap-2 px-2.5 py-1 text-[11px] text-text-muted">
          {isError ? (
            <AlertTriangle size={11} className="text-error shrink-0" />
          ) : (
            <Check size={11} className="text-success shrink-0" />
          )}
          <span className="font-medium shrink-0">{isError ? "Error" : "Result"}</span>
        </div>
        <div className="border-t border-border-subtle/20 px-2.5 py-1.5">
          <pre className="text-[10px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {content}
          </pre>
        </div>
      </div>
    );
  }

  return (
    <AccordionItem value={`block-${index}`} className={`rounded-md border mb-1.5 ${isError ? "border-error/20 bg-error/5" : "border-border-subtle/30 bg-bg-surface/20"}`}>
      <AccordionTrigger className="px-2.5 py-1 text-[11px] hover:no-underline hover:text-text-secondary [&_[data-slot=accordion-trigger-icon]]:size-2.5 [&_[data-slot=accordion-trigger-icon]]:text-text-muted">
        <div className="flex items-center gap-2 flex-1 min-w-0 mr-1">
          {isError ? (
            <AlertTriangle size={11} className="text-error shrink-0" />
          ) : (
            <Check size={11} className="text-success shrink-0" />
          )}
          <span className="font-medium text-text-muted shrink-0">{isError ? "Error" : "Result"}</span>
          <span className="truncate text-text-muted/60 group-aria-expanded/accordion-trigger:hidden">{content.slice(0, 60)}</span>
        </div>
      </AccordionTrigger>
      <AccordionContent>
        <div className="border-t border-border-subtle/20 px-2.5 py-1.5">
          <pre className="text-[10px] text-text-muted leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">
            {content}
          </pre>
        </div>
      </AccordionContent>
    </AccordionItem>
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

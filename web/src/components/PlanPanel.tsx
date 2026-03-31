import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  Check,
  FileCode,
  HelpCircle,
  Layers,
  Zap,
} from "lucide-react";
import type {
  PlanComplexity,
  PlanPhase,
  PlanTask,
  StructuredPlan,
  TaskEffort,
} from "../types";

/* ── Config ───────────────────────────────────────────────────── */

const complexityConfig: Record<
  PlanComplexity,
  { color: string; bg: string; label: string }
> = {
  low: { color: "text-emerald-400", bg: "bg-emerald-500/10", label: "Low complexity" },
  medium: { color: "text-amber-400", bg: "bg-amber-500/10", label: "Medium complexity" },
  high: { color: "text-red-400", bg: "bg-red-500/10", label: "High complexity" },
};

const effortConfig: Record<TaskEffort, { color: string; label: string }> = {
  small: { color: "text-emerald-400", label: "S" },
  medium: { color: "text-amber-400", label: "M" },
  large: { color: "text-red-400", label: "L" },
};

/* ── PlanPanel ────────────────────────────────────────────────── */

export default function PlanPanel({ plan }: { plan: StructuredPlan }) {
  const [copied, setCopied] = useState(false);
  const complexity = complexityConfig[plan.complexity];

  const totalTasks = plan.phases.reduce((sum, p) => sum + p.tasks.length, 0);
  const totalFiles = new Set(
    plan.phases.flatMap((p) => p.tasks.flatMap((t) => t.files)),
  ).size;

  const handleCopyMarkdown = async () => {
    const md = planToMarkdown(plan);
    await navigator.clipboard.writeText(md);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Title + overview */}
      <div className="rounded-lg border border-border-subtle bg-bg-surface/50 p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-accent shrink-0" />
            <h3 className="text-sm font-semibold text-text-primary font-display">
              {plan.title}
            </h3>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${complexity.color} ${complexity.bg}`}
            >
              {complexity.label}
            </span>
            <button
              onClick={handleCopyMarkdown}
              className="rounded-md p-1 text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors"
              title="Copy as markdown"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          {plan.overview}
        </p>
        <div className="mt-2 flex items-center gap-3 text-[10px] text-text-muted">
          <span>{plan.phases.length} phases</span>
          <span>{totalTasks} tasks</span>
          <span>{totalFiles} files</span>
          {plan.risks.length > 0 && (
            <span className="text-amber-400">
              {plan.risks.length} risk{plan.risks.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Phases */}
      <div className="space-y-2">
        {plan.phases.map((phase, i) => (
          <PhaseCard key={phase.id} phase={phase} index={i} />
        ))}
      </div>

      {/* Risks */}
      {plan.risks.length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
          <div className="flex items-center gap-1.5 mb-1.5">
            <AlertTriangle size={13} className="text-amber-400" />
            <span className="text-xs font-medium text-amber-400">Risks</span>
          </div>
          <ul className="space-y-1">
            {plan.risks.map((risk, i) => (
              <li
                key={i}
                className="flex items-start gap-1.5 text-xs text-text-secondary"
              >
                <span className="mt-1.5 h-1 w-1 rounded-full bg-amber-400/60 shrink-0" />
                {risk}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Open questions */}
      {plan.open_questions.length > 0 && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3">
          <div className="flex items-center gap-1.5 mb-1.5">
            <HelpCircle size={13} className="text-blue-400" />
            <span className="text-xs font-medium text-blue-400">
              Open Questions
            </span>
          </div>
          <ul className="space-y-1">
            {plan.open_questions.map((q, i) => (
              <li
                key={i}
                className="flex items-start gap-1.5 text-xs text-text-secondary"
              >
                <span className="mt-1.5 h-1 w-1 rounded-full bg-blue-400/60 shrink-0" />
                {q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── PhaseCard ─────────────────────────────────────────────────── */

function PhaseCard({ phase, index }: { phase: PlanPhase; index: number }) {
  const [expanded, setExpanded] = useState(index === 0); // First phase open by default

  return (
    <div className="rounded-lg border border-border-subtle overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-bg-hover transition-colors"
      >
        {expanded ? (
          <ChevronDown size={14} className="text-text-muted shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-text-muted shrink-0" />
        )}
        <CircleDot size={12} className="text-accent shrink-0" />
        <span className="text-[10px] font-mono text-text-muted shrink-0">
          P{index + 1}
        </span>
        <span className="text-xs font-medium text-text-primary truncate flex-1">
          {phase.name}
        </span>
        <span className="text-[10px] text-text-muted shrink-0">
          {phase.tasks.length} task{phase.tasks.length !== 1 ? "s" : ""}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border-subtle bg-bg-surface/30 animate-fade-in">
          <p className="px-3 pt-2 pb-1.5 text-xs text-text-secondary">
            {phase.description}
          </p>
          <div className="px-3 pb-2.5 space-y-1.5">
            {phase.tasks.map((task) => (
              <TaskCard key={task.id} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── TaskCard ──────────────────────────────────────────────────── */

function TaskCard({ task }: { task: PlanTask }) {
  const [expanded, setExpanded] = useState(false);
  const effort = effortConfig[task.effort];

  return (
    <div className="rounded-md border border-border-subtle bg-bg-primary">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left hover:bg-bg-hover/50 transition-colors"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-text-muted shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-text-muted shrink-0" />
        )}
        <Zap size={10} className="text-text-muted shrink-0" />
        <span className="text-[11px] text-text-primary truncate flex-1">
          {task.title}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-medium ${effort.color} bg-bg-surface`}
        >
          {effort.label}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border-subtle px-2.5 py-2 space-y-1.5 animate-fade-in">
          <p className="text-[11px] text-text-secondary leading-relaxed">
            {task.description}
          </p>
          {task.files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {task.files.map((f) => (
                <span
                  key={f}
                  className="inline-flex items-center gap-0.5 rounded bg-bg-elevated px-1.5 py-0.5 text-[9px] font-mono text-text-muted"
                >
                  <FileCode size={8} />
                  {f}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Markdown export ──────────────────────────────────────────── */

function planToMarkdown(plan: StructuredPlan): string {
  const lines: string[] = [
    `# ${plan.title}`,
    "",
    plan.overview,
    "",
    `**Complexity:** ${plan.complexity}`,
    "",
  ];

  for (const phase of plan.phases) {
    lines.push(`## ${phase.name}`, "", phase.description, "");
    for (const task of phase.tasks) {
      lines.push(`### ${task.title} [${task.effort}]`, "", task.description);
      if (task.files.length) {
        lines.push("", "Files:", ...task.files.map((f) => `- \`${f}\``));
      }
      lines.push("");
    }
  }

  if (plan.risks.length) {
    lines.push("## Risks", "", ...plan.risks.map((r) => `- ${r}`), "");
  }
  if (plan.open_questions.length) {
    lines.push(
      "## Open Questions",
      "",
      ...plan.open_questions.map((q) => `- ${q}`),
      "",
    );
  }

  return lines.join("\n");
}

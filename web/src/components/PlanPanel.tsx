import { useState } from "react";
import {
  AlertTriangle,
  CircleDot,
  Copy,
  Check,
  FileCode,
  HelpCircle,
  Layers,
  Save,
  Zap,
} from "lucide-react";
import { useStore } from "../store";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardAction, CardDescription, CardContent } from "@/components/ui/card";
import type {
  PlanComplexity,
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
  const [saving, setSaving] = useState(false);
  const createDocument = useStore((s) => s.createDocument);
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

  const handleSaveAsDocument = async () => {
    setSaving(true);
    const md = planToMarkdown(plan);
    await createDocument(plan.title, md, "plan");
    setSaving(false);
  };

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Title + overview */}
      <Card size="sm" className="ring-0 rounded-lg border border-border-subtle bg-bg-surface/50">
        <CardHeader className="p-4 pb-0">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold text-text-primary font-display">
            <Layers size={16} className="text-accent shrink-0" />
            {plan.title}
          </CardTitle>
          <CardAction className="flex items-center gap-2">
            <Badge variant="secondary" className={`h-5 ${complexity.color} ${complexity.bg}`}>
              {complexity.label}
            </Badge>
            <button
              onClick={handleSaveAsDocument}
              disabled={saving}
              className="rounded-md p-1 text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-50"
              title="Save as document"
            >
              <Save size={13} className={saving ? "animate-pulse" : ""} />
            </button>
            <button
              onClick={handleCopyMarkdown}
              className="rounded-md p-1 text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors"
              title="Copy as markdown"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </CardAction>
          <CardDescription className="text-xs text-text-secondary leading-relaxed">
            {plan.overview}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="flex items-center gap-3 text-[10px] text-text-muted">
            <span>{plan.phases.length} phases</span>
            <span>{totalTasks} tasks</span>
            <span>{totalFiles} files</span>
            {plan.risks.length > 0 && (
              <span className="text-amber-400">
                {plan.risks.length} risk{plan.risks.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Phases */}
      <Accordion defaultValue={["phase-0"]} className="space-y-2">
        {plan.phases.map((phase, i) => (
          <AccordionItem
            key={phase.id}
            value={`phase-${i}`}
            className="rounded-lg border border-border-subtle overflow-hidden"
          >
            <AccordionTrigger className="px-3 py-2.5 hover:no-underline hover:bg-bg-hover [&_[data-slot=accordion-trigger-icon]]:text-text-muted">
              <div className="flex items-center gap-2 flex-1 min-w-0 mr-2">
                <CircleDot size={12} className="text-accent shrink-0" />
                <span className="text-[10px] font-mono text-text-muted shrink-0">
                  P{i + 1}
                </span>
                <span className="text-xs font-medium text-text-primary truncate flex-1">
                  {phase.name}
                </span>
                <Badge variant="secondary" className="h-4 px-1.5 text-[10px] text-text-muted shrink-0">
                  {phase.tasks.length} task{phase.tasks.length !== 1 ? "s" : ""}
                </Badge>
              </div>
            </AccordionTrigger>
            <AccordionContent>
              <div className="border-t border-border-subtle bg-bg-surface/30">
                <p className="px-3 pt-2 pb-1.5 text-xs text-text-secondary">
                  {phase.description}
                </p>
                <div className="px-3 pb-2.5">
                  <Accordion className="space-y-1.5">
                    {phase.tasks.map((task) => (
                      <TaskItem key={task.id} task={task} />
                    ))}
                  </Accordion>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>

      {/* Risks */}
      {plan.risks.length > 0 && (
        <Alert className="border-amber-500/20 bg-amber-500/5 [&>svg]:text-amber-400">
          <AlertTriangle />
          <AlertTitle className="text-xs font-medium text-amber-400">Risks</AlertTitle>
          <AlertDescription>
            <ul className="space-y-1 mt-1">
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
          </AlertDescription>
        </Alert>
      )}

      {/* Open questions */}
      {plan.open_questions.length > 0 && (
        <Alert className="border-blue-500/20 bg-blue-500/5 [&>svg]:text-blue-400">
          <HelpCircle />
          <AlertTitle className="text-xs font-medium text-blue-400">Open Questions</AlertTitle>
          <AlertDescription>
            <ul className="space-y-1 mt-1">
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
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/* ── TaskItem (Accordion) ────────────────────────────────────── */

function TaskItem({ task }: { task: PlanTask }) {
  const effort = effortConfig[task.effort];

  return (
    <AccordionItem
      value={task.id}
      className="rounded-md border border-border-subtle bg-bg-primary"
    >
      <AccordionTrigger className="px-2.5 py-2 hover:no-underline hover:bg-bg-hover/50 text-xs [&_[data-slot=accordion-trigger-icon]]:text-text-muted [&_[data-slot=accordion-trigger-icon]]:size-3">
        <div className="flex items-center gap-2 flex-1 min-w-0 mr-2">
          <Zap size={10} className="text-text-muted shrink-0" />
          <span className="text-[11px] text-text-primary truncate flex-1">
            {task.title}
          </span>
          <Badge
            variant="secondary"
            className={`h-4 px-1.5 text-[9px] font-mono font-medium ${effort.color}`}
          >
            {effort.label}
          </Badge>
        </div>
      </AccordionTrigger>
      <AccordionContent>
        <div className="border-t border-border-subtle px-2.5 py-2 space-y-1.5">
          <p className="text-[11px] text-text-secondary leading-relaxed">
            {task.description}
          </p>
          {task.files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {task.files.map((f) => (
                <Badge
                  key={f}
                  variant="secondary"
                  className="h-4 gap-0.5 px-1.5 text-[9px] font-mono text-text-muted"
                >
                  <FileCode size={8} />
                  {f}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

/* ── Markdown export ──────────────────────────────────────────── */

export function planToMarkdown(plan: StructuredPlan): string {
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

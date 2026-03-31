import {
  MessageSquare,
  Code2,
  Search,
  BookOpen,
  ShieldCheck,
  Map,
  GitPullRequest,
  Zap,
} from "lucide-react";
import { useStore } from "../store";
import type { WorkflowKind } from "../types";
import PRSelector from "./PRSelector";

const workflows: {
  id: WorkflowKind;
  label: string;
  icon: typeof MessageSquare;
  hint: string;
}[] = [
  {
    id: "prompt",
    label: "Chat",
    icon: MessageSquare,
    hint: "Ask questions, get explanations, brainstorm solutions",
  },
  {
    id: "patch",
    label: "Code",
    icon: Code2,
    hint: "Write code changes — apply to your repo and optionally open a PR",
  },
  {
    id: "review",
    label: "Review",
    icon: Search,
    hint: "Select a PR for structured review with actionable findings",
  },
  {
    id: "docs",
    label: "Docs",
    icon: BookOpen,
    hint: "Generate or update READMEs, API docs, ADRs, or changelogs",
  },
  {
    id: "audit",
    label: "Audit",
    icon: ShieldCheck,
    hint: "Security and quality audit with structured findings",
  },
  {
    id: "plan",
    label: "Plan",
    icon: Map,
    hint: "Create a phased implementation plan with tasks and risks",
  },
];

export default function WorkflowPills() {
  const workflow = useStore((s) => s.workflow);
  const setWorkflow = useStore((s) => s.setWorkflow);
  const writeChanges = useStore((s) => s.writeChanges);
  const setWriteChanges = useStore((s) => s.setWriteChanges);
  const openPR = useStore((s) => s.openPR);
  const setOpenPR = useStore((s) => s.setOpenPR);
  const autoAccept = useStore((s) => s.autoAccept);
  const setAutoAccept = useStore((s) => s.setAutoAccept);
  const active = workflows.find((w) => w.id === workflow);

  const handleWriteChanges = (checked: boolean) => {
    setWriteChanges(checked);
    // Can't open PR without applying changes
    if (!checked) setOpenPR(false);
  };

  const handleOpenPR = (checked: boolean) => {
    setOpenPR(checked);
    // Opening a PR requires applying changes
    if (checked) setWriteChanges(true);
  };

  return (
    <div className="mb-2">
      <div className="flex flex-wrap items-center gap-1 mb-1">
        {workflows.map((w) => (
          <button
            key={w.id}
            onClick={() => setWorkflow(w.id)}
            className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              workflow === w.id
                ? "bg-accent text-bg-deep"
                : "bg-bg-surface text-text-secondary hover:bg-bg-elevated hover:text-text-primary"
            }`}
          >
            <w.icon size={12} />
            {w.label}
          </button>
        ))}

        {/* Auto-accept toggle */}
        <label className="ml-3 flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary" title="Auto-approve all tool usage (no permission prompts)">
          <input
            type="checkbox"
            checked={autoAccept}
            onChange={(e) => setAutoAccept(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border-default accent-accent"
          />
          <Zap size={12} />
          Auto-accept
        </label>

        {/* Code workflow toggles */}
        {workflow === "patch" && (
          <>
            <label className="ml-2 flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={writeChanges}
                onChange={(e) => handleWriteChanges(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border-default accent-accent"
              />
              Apply changes
            </label>
            <label className="ml-2 flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary" title="Create a branch, commit, push, and open a pull request">
              <input
                type="checkbox"
                checked={openPR}
                onChange={(e) => handleOpenPR(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border-default accent-accent"
              />
              <GitPullRequest size={12} />
              Open PR
            </label>
          </>
        )}

      </div>

      {/* Mode hint */}
      {active && (
        <p className="text-[10px] text-text-muted mb-1 pl-1">{active.hint}</p>
      )}

      {/* PR selector — only for review workflow */}
      {workflow === "review" && <PRSelector />}
    </div>
  );
}

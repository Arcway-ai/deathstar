import { MessageSquare, FileCode, GitPullRequest, Search } from "lucide-react";
import { useStore } from "../store";
import type { WorkflowKind } from "../types";

const workflows: { id: WorkflowKind; label: string; icon: typeof MessageSquare }[] = [
  { id: "prompt", label: "Chat", icon: MessageSquare },
  { id: "patch", label: "Patch", icon: FileCode },
  { id: "review", label: "Review", icon: Search },
  { id: "pr", label: "PR", icon: GitPullRequest },
];

export default function WorkflowPills() {
  const workflow = useStore((s) => s.workflow);
  const setWorkflow = useStore((s) => s.setWorkflow);
  const writeChanges = useStore((s) => s.writeChanges);
  const setWriteChanges = useStore((s) => s.setWriteChanges);

  return (
    <div className="mb-2 flex items-center gap-1">
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

      {/* Write changes toggle — only for patch workflow */}
      {workflow === "patch" && (
        <label className="ml-3 flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={writeChanges}
            onChange={(e) => setWriteChanges(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border-default accent-accent"
          />
          Apply changes
        </label>
      )}
    </div>
  );
}

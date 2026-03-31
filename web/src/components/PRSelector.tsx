import { useEffect, useRef, useState } from "react";
import {
  GitPullRequest,
  ChevronDown,
  ExternalLink,
  GitBranch,
  Loader2,
  X,
} from "lucide-react";
import { useStore } from "../store";

export default function PRSelector() {
  const pullRequests = useStore((s) => s.pullRequests);
  const pullRequestsLoading = useStore((s) => s.pullRequestsLoading);
  const selectedPR = useStore((s) => s.selectedPR);
  const loadPullRequests = useStore((s) => s.loadPullRequests);
  const selectPR = useStore((s) => s.selectPR);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Load PRs on mount
  useEffect(() => {
    if (pullRequests.length === 0) {
      loadPullRequests();
    }
  }, [pullRequests.length, loadPullRequests]);

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative mb-2">
      {/* Selected PR badge or trigger */}
      <button
        onClick={() => setOpen(!open)}
        className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
          selectedPR
            ? "border-accent/30 bg-accent/5 text-text-primary"
            : "border-border-subtle bg-bg-surface text-text-muted hover:border-border-default hover:text-text-secondary"
        }`}
      >
        <GitPullRequest size={14} className={selectedPR ? "text-accent" : ""} />
        {selectedPR ? (
          <span className="flex-1 truncate">
            <span className="text-text-muted">#{selectedPR.number}</span>{" "}
            {selectedPR.title}
          </span>
        ) : pullRequestsLoading ? (
          <span className="flex items-center gap-1.5 flex-1">
            <Loader2 size={12} className="animate-spin" />
            Loading PRs...
          </span>
        ) : (
          <span className="flex-1">Select a pull request to review...</span>
        )}
        {selectedPR ? (
          <X
            size={14}
            className="shrink-0 text-text-muted hover:text-text-primary"
            onClick={(e) => {
              e.stopPropagation();
              selectPR(null);
            }}
          />
        ) : (
          <ChevronDown size={14} className="shrink-0" />
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 bottom-full z-30 mb-1 max-h-64 overflow-y-auto rounded-lg border border-border-subtle bg-bg-elevated shadow-xl animate-fade-in">
          {pullRequests.length === 0 && !pullRequestsLoading ? (
            <div className="px-3 py-4 text-center text-xs text-text-muted">
              No open pull requests found.
            </div>
          ) : (
            pullRequests.map((pr) => (
              <button
                key={pr.number}
                onClick={() => {
                  selectPR(pr);
                  setOpen(false);
                }}
                className={`flex w-full items-start gap-2.5 border-b border-border-subtle px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-bg-hover ${
                  selectedPR?.number === pr.number ? "bg-accent/5" : ""
                }`}
              >
                <GitPullRequest
                  size={14}
                  className={`mt-0.5 shrink-0 ${pr.draft ? "text-text-muted" : "text-success"}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-text-muted">#{pr.number}</span>
                    <span className="text-xs font-medium text-text-primary truncate">
                      {pr.title}
                    </span>
                    {pr.draft && (
                      <span className="rounded bg-bg-surface px-1 py-0.5 text-[9px] text-text-muted">
                        Draft
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                    <span className="flex items-center gap-0.5">
                      <GitBranch size={9} />
                      {pr.head_branch}
                    </span>
                    <span>{pr.user}</span>
                    {(pr.additions != null && pr.deletions != null && (pr.additions > 0 || pr.deletions > 0)) && (
                      <span>
                        <span className="text-success">+{pr.additions}</span>{" "}
                        <span className="text-error">-{pr.deletions}</span>
                      </span>
                    )}
                  </div>
                </div>
                <a
                  href={pr.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="mt-0.5 shrink-0 text-text-muted hover:text-accent"
                >
                  <ExternalLink size={11} />
                </a>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

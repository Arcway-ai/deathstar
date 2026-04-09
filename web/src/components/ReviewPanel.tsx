import {
  AlertTriangle,
  Bug,
  Check,
  CheckCircle,
  ExternalLink,
  FileCode,
  GitCommit,
  Lightbulb,
  Loader2,
  MessageSquare,
  Shield,
  X,
  XCircle,
} from "lucide-react";
import { useStore } from "../store";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type {
  FindingAction,
  ReviewFinding,
  ReviewSeverity,
  ReviewVerdict,
  StructuredReview,
} from "../types";

/* ── Severity config ──────────────────────────────────────────── */

const severityConfig: Record<
  ReviewSeverity,
  { icon: typeof Bug; color: string; bg: string; border: string; label: string }
> = {
  error: {
    icon: Bug,
    color: "text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    label: "Error",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    label: "Warning",
  },
  suggestion: {
    icon: Lightbulb,
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    label: "Suggestion",
  },
  nitpick: {
    icon: MessageSquare,
    color: "text-text-muted",
    bg: "bg-bg-surface",
    border: "border-border-subtle",
    label: "Nitpick",
  },
};

const verdictConfig: Record<
  ReviewVerdict,
  { icon: typeof CheckCircle; color: string; bg: string; label: string }
> = {
  approve: {
    icon: CheckCircle,
    color: "text-emerald-400",
    bg: "bg-emerald-500/10",
    label: "Approve",
  },
  request_changes: {
    icon: XCircle,
    color: "text-red-400",
    bg: "bg-red-500/10",
    label: "Changes Requested",
  },
  comment: {
    icon: MessageSquare,
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    label: "Comment",
  },
};

/* ── Main ReviewPanel ─────────────────────────────────────────── */

export default function ReviewPanel({ review }: { review: StructuredReview }) {
  const findingActions = useStore((s) => s.findingActions);
  const setFindingAction = useStore((s) => s.setFindingAction);
  const bulkSetFindingAction = useStore((s) => s.bulkSetFindingAction);
  const postReviewToGitHub = useStore((s) => s.postReviewToGitHub);
  const applySuggestions = useStore((s) => s.applySuggestions);
  const reviewPosting = useStore((s) => s.reviewPosting);
  const reviewApplying = useStore((s) => s.reviewApplying);
  const selectedPR = useStore((s) => s.selectedPR);

  const verdict = verdictConfig[review.verdict];
  const VerdictIcon = verdict.icon;

  const acceptedCount = Object.values(findingActions).filter(
    (a) => a === "accepted",
  ).length;
  const rejectedCount = Object.values(findingActions).filter(
    (a) => a === "rejected",
  ).length;
  const pendingCount = Object.values(findingActions).filter(
    (a) => a === "pending",
  ).length;
  const hasCodeSuggestions = review.findings.some(
    (f) =>
      f.suggested_code != null &&
      f.original_code != null &&
      findingActions[f.id] === "accepted",
  );

  const bySeverity = review.findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    },
    {} as Record<ReviewSeverity, number>,
  );

  return (
    <div className="space-y-3 animate-fade-in">
      {/* Verdict + Summary */}
      <Card size="sm" className={`ring-0 rounded-lg border border-border-subtle ${verdict.bg}`}>
        <CardHeader className="p-4 pb-0">
          <CardTitle className="flex items-center gap-2">
            <VerdictIcon size={18} className={verdict.color} />
            <span className={`text-sm font-semibold ${verdict.color}`}>
              {verdict.label}
            </span>
            <div className="ml-auto flex items-center gap-2">
              {(["error", "warning", "suggestion", "nitpick"] as ReviewSeverity[]).map(
                (sev) =>
                  bySeverity[sev] ? (
                    <Badge
                      key={sev}
                      variant="secondary"
                      className={`h-4 px-1.5 text-[10px] ${severityConfig[sev].color}`}
                    >
                      {bySeverity[sev]} {severityConfig[sev].label.toLowerCase()}
                      {bySeverity[sev] > 1 ? "s" : ""}
                    </Badge>
                  ) : null,
              )}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-sm text-text-secondary leading-relaxed">
            {review.summary}
          </p>
        </CardContent>
      </Card>

      {/* Bulk actions */}
      {review.findings.length > 0 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-text-muted">
            {acceptedCount} accepted · {rejectedCount} rejected · {pendingCount}{" "}
            pending
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => bulkSetFindingAction("accepted")}
              className="flex items-center gap-1 rounded-md bg-emerald-500/10 px-2.5 py-1 text-emerald-400 hover:bg-emerald-500/20 transition-colors"
            >
              <Check size={12} />
              Accept All
            </button>
            <button
              onClick={() => bulkSetFindingAction("rejected")}
              className="flex items-center gap-1 rounded-md bg-red-500/10 px-2.5 py-1 text-red-400 hover:bg-red-500/20 transition-colors"
            >
              <X size={12} />
              Reject All
            </button>
            <button
              onClick={() => bulkSetFindingAction("pending")}
              className="flex items-center gap-1 rounded-md bg-bg-surface px-2.5 py-1 text-text-muted hover:bg-bg-hover transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Findings list */}
      <Accordion>
        {review.findings.map((finding) => (
          <FindingItem
            key={finding.id}
            finding={finding}
            action={findingActions[finding.id] || "pending"}
            onAction={(a) => setFindingAction(finding.id, a)}
          />
        ))}
      </Accordion>

      {review.findings.length === 0 && (
        <Card size="sm" className="ring-0 rounded-lg border border-emerald-500/20 bg-emerald-500/5">
          <CardContent className="px-4 py-6 text-center">
            <CheckCircle size={24} className="mx-auto mb-2 text-emerald-400" />
            <p className="text-sm text-emerald-400 font-medium">
              No issues found
            </p>
            <p className="text-xs text-text-muted mt-1">
              This PR looks good to go.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Action buttons */}
      {review.findings.length > 0 && selectedPR && (
        <div className="flex items-center gap-2 border-t border-border-subtle pt-3">
          <button
            onClick={postReviewToGitHub}
            disabled={reviewPosting || acceptedCount === 0}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-bg-deep hover:bg-accent-hover transition-colors disabled:opacity-40 disabled:pointer-events-none"
          >
            {reviewPosting ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Shield size={12} />
            )}
            Post Review to GitHub
            {acceptedCount > 0 && (
              <Badge variant="secondary" className="h-4 px-1.5 text-[10px] bg-bg-deep/20">
                {acceptedCount}
              </Badge>
            )}
          </button>

          {hasCodeSuggestions && (
            <button
              onClick={applySuggestions}
              disabled={reviewApplying}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              {reviewApplying ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <GitCommit size={12} />
              )}
              Apply Suggestions
            </button>
          )}

          <a
            href={selectedPR.url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex items-center gap-1 text-[10px] text-text-muted hover:text-accent transition-colors"
          >
            <ExternalLink size={10} />
            View PR
          </a>
        </div>
      )}
    </div>
  );
}

/* ── FindingItem (Accordion) ─────────────────────────────────── */

function FindingItem({
  finding,
  action,
  onAction,
}: {
  finding: ReviewFinding;
  action: FindingAction;
  onAction: (a: FindingAction) => void;
}) {
  const sev = severityConfig[finding.severity];
  const SevIcon = sev.icon;

  const actionStyles: Record<FindingAction, string> = {
    pending: "border-border-subtle",
    accepted: "border-emerald-500/30 bg-emerald-500/5",
    rejected: "border-red-500/20 bg-red-500/5 opacity-60",
  };

  return (
    <AccordionItem
      value={finding.id}
      className={`rounded-lg border transition-all duration-200 mb-2 ${actionStyles[action]}`}
    >
      {/* Header row - custom trigger with action buttons */}
      <div className="flex items-start gap-2 px-3 py-2.5">
        <AccordionTrigger className="flex-1 p-0 hover:no-underline [&_[data-slot=accordion-trigger-icon]]:size-3.5 [&_[data-slot=accordion-trigger-icon]]:text-text-muted">
          <div className="flex items-start gap-2 flex-1 min-w-0 mr-2">
            <SevIcon size={14} className={`mt-0.5 shrink-0 ${sev.color}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className={`h-4 px-1.5 text-[10px] ${sev.color} ${sev.bg}`}>
                  {sev.label}
                </Badge>
                <span className="text-xs font-medium text-text-primary truncate">
                  {finding.title}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                <span className="flex items-center gap-0.5">
                  <FileCode size={9} />
                  {finding.file}
                </span>
                {finding.line_start != null && (
                  <span>
                    L{finding.line_start}
                    {finding.line_end && finding.line_end !== finding.line_start
                      ? `–${finding.line_end}`
                      : ""}
                  </span>
                )}
              </div>
            </div>
          </div>
        </AccordionTrigger>

        {/* Accept / Reject buttons outside the trigger */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() =>
              onAction(action === "accepted" ? "pending" : "accepted")
            }
            className={`rounded-md p-1.5 transition-colors ${
              action === "accepted"
                ? "bg-emerald-500/20 text-emerald-400"
                : "text-text-muted hover:bg-emerald-500/10 hover:text-emerald-400"
            }`}
            title="Accept"
          >
            <Check size={13} />
          </button>
          <button
            onClick={() =>
              onAction(action === "rejected" ? "pending" : "rejected")
            }
            className={`rounded-md p-1.5 transition-colors ${
              action === "rejected"
                ? "bg-red-500/20 text-red-400"
                : "text-text-muted hover:bg-red-500/10 hover:text-red-400"
            }`}
            title="Reject"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* Expanded details */}
      <AccordionContent>
        <div className="border-t border-border-subtle px-3 py-2.5 space-y-2">
          <p className="text-xs text-text-secondary leading-relaxed">
            {finding.body}
          </p>

          {finding.original_code && (
            <div className="space-y-1">
              <span className="text-[10px] font-medium text-red-400/80">
                Current code:
              </span>
              <pre className="rounded-md bg-bg-deep border border-red-500/10 px-3 py-2 text-[11px] font-mono text-text-secondary overflow-x-auto whitespace-pre-wrap break-all">
                {finding.original_code}
              </pre>
            </div>
          )}

          {finding.suggested_code && (
            <div className="space-y-1">
              <span className="text-[10px] font-medium text-emerald-400/80">
                Suggested fix:
              </span>
              <pre className="rounded-md bg-bg-deep border border-emerald-500/10 px-3 py-2 text-[11px] font-mono text-text-secondary overflow-x-auto whitespace-pre-wrap break-all">
                {finding.suggested_code}
              </pre>
            </div>
          )}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

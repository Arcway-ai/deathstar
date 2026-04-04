/* ── Domain types matching Pydantic models + frontend-only types ─── */

export type WorkflowKind = "prompt" | "patch" | "pr" | "review" | "docs" | "audit" | "plan";
export type ProviderName = "anthropic";

export interface RepoInfo {
  name: string;
  branch: string;
  dirty: boolean;
}

export interface GitHubRepo {
  full_name: string;
  name: string;
  description: string | null;
  default_branch: string;
  private: boolean;
  updated_at: string;
  language: string | null;
}

export interface PullRequestSummary {
  number: number;
  title: string;
  state: string;
  user: string;
  head_branch: string;
  base_branch: string;
  updated_at: string;
  additions: number | null;
  deletions: number | null;
  changed_files: number | null;
  draft: boolean;
  url: string;
}

/* ── Structured Review ────────────────────────────────────────── */

export type ReviewSeverity = "error" | "warning" | "suggestion" | "nitpick";
export type ReviewVerdict = "approve" | "request_changes" | "comment";

export interface ReviewFinding {
  id: string;
  file: string;
  line_start: number | null;
  line_end: number | null;
  severity: ReviewSeverity;
  title: string;
  body: string;
  original_code: string | null;
  suggested_code: string | null;
}

export interface StructuredReview {
  summary: string;
  verdict: ReviewVerdict;
  findings: ReviewFinding[];
}

export type FindingAction = "pending" | "accepted" | "rejected";

export interface ApplySuggestionsResponse {
  commit_sha: string;
  files_changed: number;
  commit_url: string;
  applied: string[];
  skipped: string[];
}

/* ── Structured Plan ──────────────────────────────────────────── */

export type PlanComplexity = "low" | "medium" | "high";
export type TaskEffort = "small" | "medium" | "large";

export interface PlanTask {
  id: string;
  title: string;
  description: string;
  files: string[];
  effort: TaskEffort;
}

export interface PlanPhase {
  id: string;
  name: string;
  description: string;
  tasks: PlanTask[];
}

export interface StructuredPlan {
  title: string;
  overview: string;
  complexity: PlanComplexity;
  phases: PlanPhase[];
  risks: string[];
  open_questions: string[];
}

export interface RepoContext {
  branch: string;
  recent_commits: string[];
  claude_md: string | null;
  file_tree: string[];
  conflict_files: string[];
  branch_switched_from: string | null;
}

export interface UsageMetrics {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

export interface ChatRequest {
  repo: string;
  message: string;
  conversation_id?: string;
  workflow: WorkflowKind;
  provider?: ProviderName;
  model?: string;
  system?: string;
  write_changes: boolean;
  pr_url?: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  content: string | null;
  workflow: WorkflowKind;
  provider: ProviderName;
  model: string;
  duration_ms: number;
  usage: UsageMetrics | null;
  cost_usd: number | null;
  error: ErrorEnvelope | null;
  status: "succeeded" | "failed";
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  workflow?: WorkflowKind;
  provider?: ProviderName;
  model?: string;
  duration_ms?: number;
  usage?: UsageMetrics | null;
  agent_blocks?: AgentContentBlock[] | null;
}

export interface ConversationSummary {
  id: string;
  repo: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
  branch: string | null;
  branches: string[];
}

export interface ConversationDetail {
  id: string;
  repo: string;
  title: string;
  messages: ConversationMessage[];
  created_at: string;
  updated_at: string;
  branch: string | null;
  branches: string[];
}

export interface ProviderStatus {
  configured: boolean;
  default_model: string;
}

export interface MemoryEntry {
  id: string;
  repo: string;
  content: string;
  source_message_id: string;
  source_prompt: string;
  tags: string[];
  created_at: string;
}

/* ── Feedback ──────────────────────────────────────────────────── */

export type FeedbackKind = "thumbs_up" | "thumbs_down";

export interface FeedbackRequest {
  message_id: string;
  conversation_id?: string;
  kind: FeedbackKind;
  repo: string;
  content?: string;
  prompt?: string;
  comment?: string;
}

export interface FeedbackResponse {
  id: string;
  message_id: string;
  kind: FeedbackKind;
  repo: string;
  created_at: string;
}

/* ── Persona ───────────────────────────────────────────────────── */

export interface Persona {
  id: string;
  name: string;
  shortName: string;
  description: string;
  icon: string;
  color: string;
  systemPrompt: string;
  workflows: WorkflowKind[];
}

/* ── Agent Streaming ───────────────────────────────────────────── */

export type AgentContentBlock =
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "tool_use"; id: string; tool: string; input: Record<string, unknown> }
  | { type: "tool_result"; toolUseId: string; content: string; isError: boolean }
  | { type: "permission_request"; tool: string; input: Record<string, unknown> };

export interface AgentStreamState {
  blocks: AgentContentBlock[];
  pendingPermission: { tool: string; input: Record<string, unknown> } | null;
  isStreaming: boolean;
  startedAt: number | null;
  statusMessage: string | null;
}

export interface ServerQueueItem {
  id: string;
  conversation_id: string;
  repo: string;
  branch: string | null;
  message: string;
  workflow: WorkflowKind;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  created_at: string;
}

/* ── View state ────────────────────────────────────────────────── */

export type SidebarView = "conversations" | "memory";
export type RightPanelView = "files" | "commits";

export interface CommitInfo {
  sha: string;
  short_sha: string;
  message: string;
  author: string;
  date: string;
}
export type SettingsTab = "general" | "providers" | "memory";

/* ── Domain types matching Pydantic models + frontend-only types ─── */

export type WorkflowKind = "prompt" | "patch" | "pr" | "review";
export type ProviderName = "openai" | "anthropic" | "google" | "vertex";

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

export interface RepoContext {
  branch: string;
  recent_commits: string[];
  claude_md: string | null;
  file_tree: string[];
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
}

export interface ConversationSummary {
  id: string;
  repo: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  id: string;
  repo: string;
  title: string;
  messages: ConversationMessage[];
  created_at: string;
  updated_at: string;
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

/* ── View state ────────────────────────────────────────────────── */

export type SidebarView = "conversations" | "files" | "memory";
export type SettingsTab = "general" | "providers" | "memory";

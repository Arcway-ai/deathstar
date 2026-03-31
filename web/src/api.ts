import type {
  ApplySuggestionsResponse,
  CommitInfo,
  ConversationDetail,
  ConversationSummary,
  FeedbackRequest,
  FeedbackResponse,
  GitHubRepo,
  MemoryEntry,
  PullRequestSummary,
  RepoContext,
  RepoInfo,
  ReviewFinding,
  ReviewVerdict,
} from "./types";

const BASE = "/web/api";

/** Bootstrap session cookie (needed in Vite dev mode; no-op if cookie already set). */
export async function initSession(): Promise<void> {
  await fetch(`${BASE}/auth/session`, {
    method: "POST",
    credentials: "same-origin",
  }).catch(() => {});
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      res.status,
      (body as Record<string, string>).message || res.statusText,
      (body as Record<string, string>).code,
    );
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/* ── Repos ─────────────────────────────────────────────────────── */

export async function fetchRepos(): Promise<RepoInfo[]> {
  return request<RepoInfo[]>("/repos");
}

export async function fetchRepoTree(name: string): Promise<string[]> {
  return request<string[]>(`/repos/${encodeURIComponent(name)}/tree`);
}

export async function fetchRepoFile(
  name: string,
  path: string,
): Promise<{ path: string; content: string }> {
  return request(`/repos/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`);
}

export async function fetchRepoContext(name: string): Promise<RepoContext> {
  return request<RepoContext>(`/repos/${encodeURIComponent(name)}/context`);
}

export async function fetchBranches(
  name: string,
): Promise<{ branches: string[]; current: string }> {
  return request(`/repos/${encodeURIComponent(name)}/branches`);
}

export async function createBranch(
  name: string,
  branchName: string,
  fromBranch?: string,
): Promise<{ branch: string }> {
  return request(`/repos/${encodeURIComponent(name)}/branch`, {
    method: "POST",
    body: JSON.stringify({ branch: branchName, from_branch: fromBranch }),
  });
}

export async function checkoutBranch(
  name: string,
  branchName: string,
): Promise<{ branch: string; auto_committed?: boolean; auto_commit_branch?: string }> {
  return request(`/repos/${encodeURIComponent(name)}/checkout`, {
    method: "POST",
    body: JSON.stringify({ branch: branchName }),
  });
}

export async function quickSave(
  name: string,
  context?: string,
): Promise<{ saved: boolean; message: string; sha?: string }> {
  return request(`/repos/${encodeURIComponent(name)}/save`, {
    method: "POST",
    body: JSON.stringify(context ? { context } : {}),
  });
}

export async function deleteBranch(
  name: string,
  branchName: string,
): Promise<{ branch: string }> {
  return request(`/repos/${encodeURIComponent(name)}/branch`, {
    method: "DELETE",
    body: JSON.stringify({ branch: branchName }),
  });
}

export async function syncBranch(
  name: string,
  baseBranch = "main",
): Promise<{
  branch: string;
  base_branch: string;
  conflict: boolean;
  conflict_files: string[];
  message: string;
  up_to_date: boolean;
}> {
  return request(`/repos/${encodeURIComponent(name)}/sync`, {
    method: "POST",
    body: JSON.stringify({ base_branch: baseBranch }),
  });
}

export async function fetchWorktrees(
  name: string,
): Promise<{ path: string; branch: string; head_sha: string; is_primary: boolean }[]> {
  return request(`/repos/${encodeURIComponent(name)}/worktrees`);
}

export async function fetchCommits(
  name: string,
  limit = 30,
): Promise<CommitInfo[]> {
  return request<CommitInfo[]>(
    `/repos/${encodeURIComponent(name)}/commits?limit=${limit}`,
  );
}

/* ── GitHub ────────────────────────────────────────────────────── */

export async function fetchGitHubRepos(): Promise<GitHubRepo[]> {
  return request<GitHubRepo[]>("/github/repos");
}

export async function cloneGitHubRepo(fullName: string): Promise<{ name: string }> {
  return request("/github/clone", {
    method: "POST",
    body: JSON.stringify({ full_name: fullName }),
  });
}

/* ── Pull Requests ────────────────────────────────────────────── */

export async function fetchPullRequests(
  name: string,
  state = "open",
): Promise<PullRequestSummary[]> {
  return request<PullRequestSummary[]>(
    `/repos/${encodeURIComponent(name)}/pulls?state=${encodeURIComponent(state)}`,
  );
}

/* ── Conversations ─────────────────────────────────────────────── */

export async function fetchConversations(repo?: string, branch?: string): Promise<ConversationSummary[]> {
  const parts: string[] = [];
  if (repo) parts.push(`repo=${encodeURIComponent(repo)}`);
  if (branch) parts.push(`branch=${encodeURIComponent(branch)}`);
  const params = parts.length > 0 ? `?${parts.join("&")}` : "";
  return request<ConversationSummary[]>(`/conversations${params}`);
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`);
}

export async function deleteConversation(id: string): Promise<void> {
  await request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/* ── Claude Auth ───────────────────────────────────────────────── */

export async function fetchClaudeAuthStatus(): Promise<{
  authenticated: boolean;
  message?: string;
}> {
  return request("/claude/auth/status");
}

export async function submitClaudeToken(token: string): Promise<{
  success: boolean;
  error?: string;
  message?: string;
}> {
  return request("/claude/auth/token", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function claudeLogout(): Promise<{
  success: boolean;
  message?: string;
}> {
  return request("/claude/auth/logout", { method: "POST" });
}

/* ── Memory Bank ───────────────────────────────────────────────── */

export async function fetchMemories(repo?: string): Promise<MemoryEntry[]> {
  const params = repo ? `?repo=${encodeURIComponent(repo)}` : "";
  return request<MemoryEntry[]>(`/memory${params}`);
}

export async function saveMemory(entry: {
  repo: string;
  content: string;
  source_message_id: string;
  source_prompt: string;
  tags: string[];
}): Promise<MemoryEntry> {
  return request<MemoryEntry>("/memory", {
    method: "POST",
    body: JSON.stringify(entry),
  });
}

export async function deleteMemory(id: string): Promise<void> {
  await request(`/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/* ── Feedback ─────────────────────────────────────────────────── */

export async function saveFeedback(req: FeedbackRequest): Promise<FeedbackResponse> {
  return request<FeedbackResponse>("/feedback", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

/* ── Reviews ──────────────────────────────────────────────────── */

export async function postReviewToGitHub(params: {
  pr_url: string;
  summary: string;
  verdict: ReviewVerdict;
  findings: ReviewFinding[];
}): Promise<{ review_id: number; html_url: string; state: string }> {
  return request("/reviews/post-to-github", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function applySuggestions(params: {
  pr_url: string;
  findings: ReviewFinding[];
  commit_message?: string;
}): Promise<ApplySuggestionsResponse> {
  return request("/reviews/apply-suggestions", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

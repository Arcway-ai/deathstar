import type {
  ChatRequest,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  GitHubRepo,
  MemoryEntry,
  ProviderStatus,
  RepoContext,
  RepoInfo,
} from "./types";

const BASE = "/web/api";

function headers(): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const token = localStorage.getItem("ds_api_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers(), ...init?.headers },
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

/* ── Chat ──────────────────────────────────────────────────────── */

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

/* ── Conversations ─────────────────────────────────────────────── */

export async function fetchConversations(repo?: string): Promise<ConversationSummary[]> {
  const params = repo ? `?repo=${encodeURIComponent(repo)}` : "";
  return request<ConversationSummary[]>(`/conversations${params}`);
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`);
}

export async function deleteConversation(id: string): Promise<void> {
  await request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/* ── Providers ─────────────────────────────────────────────────── */

export async function fetchProviders(): Promise<Record<string, ProviderStatus>> {
  return request<Record<string, ProviderStatus>>("/providers");
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

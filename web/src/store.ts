import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as api from "./api";
import { AgentSocket } from "./agentSocket";
import type { AgentResult, AgentStatusEvent, RepoEventData } from "./agentSocket";
import { toast } from "./components/Toast";
import { tryParsePlan } from "./planUtils";
import { planToMarkdown } from "./components/PlanPanel";
import { defaultPersona, getPersonaById } from "./personas";
import { defaultTheme, applyTheme } from "./themes";
import type { Theme } from "./themes";
import type {
  AgentStreamState,
  ApplySuggestionsResponse,
  BranchInfo,
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  DocumentEntry,
  FindingAction,
  GitHubRepo,
  MemoryEntry,
  Persona,
  PreviewDeployment,
  ProviderName,
  ServerQueueItem,
  ProviderStatus,
  PullRequestSummary,
  RepoContext,
  RepoInfo,
  RightPanelView,
  SidebarView,
  StructuredReview,
  WorkflowKind,
} from "./types";

let _suggestionId = 0;
function withIds(suggestions: { content: string; tags: string[] }[]) {
  return suggestions.map((s) => ({ ...s, id: String(++_suggestionId) }));
}

/** Follow-up prompt sent when the agent returned malformed plan JSON. */
const RETRY_STRUCTURE_PLAN_PROMPT = [
  "Your previous response could not be parsed as valid JSON. Please try again — output ONLY a single valid JSON object with no markdown fences, no trailing commas, and no commentary before or after. Match this schema exactly:",
  "",
  "{",
  '  "title": "Short descriptive title (under 80 chars)",',
  '  "overview": "1-3 sentence summary",',
  '  "complexity": "low | medium | high",',
  '  "phases": [{ "id": "phase-1", "name": "...", "description": "...", "tasks": [{ "id": "phase-1-task-1", "title": "...", "description": "...", "files": ["path/to/file.py"], "effort": "small | medium | large" }] }],',
  '  "risks": ["Concrete risk descriptions"],',
  '  "open_questions": ["Specific questions needing answers"]',
  "}",
  "",
  "Double-check that every string is properly escaped and the JSON is valid before responding.",
].join("\n");

interface Store {
  /* ── Repos ─────────────────────────────────────────────────── */
  repos: RepoInfo[];
  selectedRepo: string | null;
  repoContext: RepoContext | null;
  repoLoading: boolean;
  fileTree: string[];
  fileContent: { path: string; content: string } | null;
  loadRepos: () => Promise<void>;
  selectRepo: (name: string) => Promise<void>;
  loadFileTree: (name: string) => Promise<void>;
  openFile: (repo: string, path: string) => Promise<void>;
  closeFile: () => void;

  /* ── Commits ─────────────────────────────────────────────── */
  commits: import("./types").CommitInfo[];
  commitsLoading: boolean;
  loadCommits: () => Promise<void>;

  /* ── Branches ─────────────────────────────────────────────── */
  branches: BranchInfo[];
  branchLoading: boolean;
  loadBranches: () => Promise<void>;
  switchBranch: (branch: string) => Promise<void>;
  createAndSwitchBranch: (branch: string) => Promise<void>;
  deleteBranch: (branch: string) => Promise<void>;
  syncBranch: (baseBranch?: string) => Promise<void>;
  quickSave: () => Promise<void>;

  /* ── GitHub ────────────────────────────────────────────────── */
  githubRepos: GitHubRepo[];
  githubLoading: boolean;
  loadGitHubRepos: () => Promise<void>;
  cloneRepo: (fullName: string) => Promise<void>;

  /* ── Pull Requests ────────────────────────────────────────── */
  pullRequests: PullRequestSummary[];
  pullRequestsLoading: boolean;
  selectedPR: PullRequestSummary | null;
  loadPullRequests: () => Promise<void>;
  selectPR: (pr: PullRequestSummary | null) => void;

  /* ── Conversations ─────────────────────────────────────────── */
  conversations: ConversationSummary[];
  activeConversation: ConversationDetail | null;
  conversationId: string | null;
  loadConversations: (repo?: string) => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  newConversation: () => void;
  deleteConversation: (id: string) => Promise<void>;

  /* ── Chat ───────────────────────────────────────────────────── */
  sending: boolean;
  sendError: string | null;
  lastFailedMessage: string | null;
  streamingText: string;
  streamingProgress: string | null;
  agentStream: AgentStreamState;
  serverQueue: ServerQueueItem[];
  loadQueue: () => Promise<void>;
  cancelQueueItem: (id: string) => Promise<void>;
  clearQueue: () => Promise<void>;
  syncAgentState: () => Promise<void>;
  sendMessage: (message: string) => Promise<void>;
  retryLastMessage: () => void;
  sendAgentInput: (text: string) => void;
  pokeAgent: () => void;
  respondToPermission: (allow: boolean) => void;
  interruptAgent: () => void;
  abortStream: (() => void) | null;

  /* ── Workflow + Persona ─────────────────────────────────────── */
  workflow: WorkflowKind;
  setWorkflow: (w: WorkflowKind) => void;
  autoAccept: boolean;
  setAutoAccept: (v: boolean) => void;
  persona: Persona;
  setPersona: (p: Persona) => void;
  /** @internal Stashed persona to restore when leaving review mode */
  _preReviewPersona?: Persona;

  /* ── Providers ──────────────────────────────────────────────── */
  providers: Record<string, ProviderStatus>;
  selectedProvider: ProviderName | null;
  selectedModel: string | null;
  loadProviders: () => Promise<void>;
  setProvider: (p: ProviderName) => void;
  setModel: (m: string | null) => void;

  /* ── Claude Auth ─────────────────────────────────────────────── */
  claudeAuth: { authenticated: boolean; message?: string; loading: boolean };
  claudeAuthSubmitting: boolean;
  checkClaudeAuth: () => Promise<void>;
  submitClaudeToken: (token: string) => Promise<boolean>;
  claudeLogout: () => Promise<void>;

  /* ── Memory Bank ────────────────────────────────────────────── */
  memories: MemoryEntry[];
  memoryDistillingId: string | null;
  loadMemories: (repo?: string) => Promise<void>;
  thumbsUp: (messageId: string, content: string, prompt: string) => Promise<void>;
  messageFeedback: Record<string, "thumbs_up">;
  deleteMemory: (id: string) => Promise<void>;

  /* ── Memory Suggestions ────────────────────────────────────── */
  suggestedMemories: { id: string; content: string; tags: string[] }[];
  suggestingMemories: boolean;
  suggestMemoriesOpen: boolean;
  setSuggestMemoriesOpen: (open: boolean) => void;
  fetchMemorySuggestions: () => Promise<void>;
  approveMemorySuggestion: (index: number) => Promise<void>;
  dismissMemorySuggestion: (index: number) => void;

  /* ── Documents ─────────────────────────────────────────────── */
  documents: DocumentEntry[];
  documentsLoading: boolean;
  pinnedDocumentIds: string[];
  loadDocuments: (repo?: string) => Promise<void>;
  createDocument: (title: string, content: string, documentType: string) => Promise<DocumentEntry | null>;
  updateDocument: (id: string, updates: { title?: string; content?: string; document_type?: string }) => Promise<void>;
  deleteDocument: (id: string) => Promise<void>;
  pinDocument: (id: string) => void;
  unpinDocument: (id: string) => void;

  /* ── Review Actions ────────────────────────────────────────── */
  activeReview: StructuredReview | null;
  findingActions: Record<string, FindingAction>;
  reviewPosting: boolean;
  reviewApplying: boolean;
  setActiveReview: (review: StructuredReview | null) => void;
  setFindingAction: (findingId: string, action: FindingAction) => void;
  bulkSetFindingAction: (action: FindingAction) => void;
  postReviewToGitHub: () => Promise<void>;
  applySuggestions: () => Promise<ApplySuggestionsResponse | null>;

  /* ── Context Files ─────────────────────────────────────────── */
  contextFiles: string[];
  pinFile: (path: string) => void;
  unpinFile: (path: string) => void;
  clearContextFiles: () => void;

  /* ── Draft Input ──────────────────────────────────────────── */
  draftInput: string;
  setDraftInput: (text: string) => void;

  /* ── Theme ─────────────────────────────────────────────────── */
  theme: Theme;
  setTheme: (t: Theme) => void;

  /* ── Superlaser ──────────────────────────────────────────────── */
  superlaserFiring: boolean;
  compacting: boolean;
  fireSuperlaser: () => void;
  stopSuperlaser: () => void;

  /* ── Preview Deployments ────────────────────────────────────── */
  previews: PreviewDeployment[];
  previewsLoading: boolean;
  previewProvidersConfigured: Record<string, boolean>;
  loadPreviews: () => Promise<void>;
  loadPreviewProviders: () => Promise<void>;
  createPreview: () => Promise<void>;
  deletePreview: (id: string) => Promise<void>;
  refreshPreview: (id: string) => Promise<void>;

  /* ── UI State ───────────────────────────────────────────────── */
  sidebarOpen: boolean;
  sidebarView: SidebarView;
  rightPanelOpen: boolean;
  rightPanelView: RightPanelView;
  settingsOpen: boolean;
  terminalOpen: boolean;
  toggleSidebar: () => void;
  setSidebarView: (v: SidebarView) => void;
  toggleRightPanel: () => void;
  setRightPanelView: (v: RightPanelView) => void;
  toggleSettings: () => void;
  toggleTerminal: () => void;
  closeTerminal: () => void;
}

export const useStore = create<Store>()(persist((set, get) => ({
  /* ── Repos ──────────────────────────────────────────────────── */
  repos: [],
  selectedRepo: null,
  repoContext: null,
  repoLoading: false,
  fileTree: [],
  fileContent: null,

  loadRepos: async () => {
    set({ repoLoading: true });
    try {
      const repos = await api.fetchRepos();
      set({ repos, repoLoading: false });
    } catch (e) {
      set({ repoLoading: false });
      toast.error("Failed to load repos", e instanceof Error ? e.message : undefined);
    }
  },

  selectRepo: async (name) => {
    set({
      selectedRepo: name,
      repoContext: null,
      fileTree: [],
      fileContent: null,
      conversationId: null,
      activeConversation: null,
      branches: [],
      commits: [],
      // Clear PR + review state so Review mode refreshes for the new repo
      pullRequests: [],
      pullRequestsLoading: false,
      selectedPR: null,
      activeReview: null,
      findingActions: {},
      // Reset streaming state when jumping to a different repo so the input
      // is immediately usable (the server agent keeps running in its worktree).
      sending: false,
      compacting: false,
      agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
    });

    // Subscribe to real-time events for this repo
    if (_agentSocket) {
      _agentSocket.subscribeEvents(name);
    }

    try {
      const [context, commits] = await Promise.all([
        api.fetchRepoContext(name),
        api.fetchCommits(name),
      ]);
      set({ repoContext: context, commits });
      // Load all conversations for this repo (no branch filter) so the
      // sidebar shows conversations from all branches.
      const conversations = await api.fetchConversations(name);
      set({ conversations });
      if (context.branch_switched_from) {
        toast.info(
          "Branch cleaned up",
          `"${context.branch_switched_from}" was deleted on remote (PR merged?). Switched to ${context.branch}.`,
        );
        await get().loadBranches();
      }
      // Fetch the branch PR so Review mode auto-selects it for the current branch
      if (context.branch) {
        api.fetchBranchPR(name, context.branch).then((pr) => {
          if (pr && get().selectedRepo === name) {
            set((s) => ({
              pullRequests: [...s.pullRequests.filter((p) => p.number !== pr.number), pr],
              // Auto-select if in review mode and no PR selected yet
              selectedPR: s.workflow === "review" && !s.selectedPR ? pr : s.selectedPR,
            }));
          }
        }).catch(() => {});
      }
      // Load preview deployments and provider status in background
      get().loadPreviews();
      get().loadPreviewProviders();
    } catch {
      // context fetch may fail if endpoint not yet available — fall back to
      // unfiltered conversations so the sidebar isn't completely empty.
      try {
        const conversations = await api.fetchConversations(name);
        set({ conversations });
      } catch { /* ignore */ }
    }
  },

  loadFileTree: async (name) => {
    try {
      const tree = await api.fetchRepoTree(name);
      set({ fileTree: tree });
    } catch { /* ignore */ }
  },

  openFile: async (repo, path) => {
    try {
      const file = await api.fetchRepoFile(repo, path);
      set({ fileContent: file });
    } catch { /* ignore */ }
  },

  closeFile: () => set({ fileContent: null }),

  /* ── Commits ──────────────────────────────────────────────── */
  commits: [],
  commitsLoading: false,

  loadCommits: async () => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    set({ commitsLoading: true });
    try {
      const commits = await api.fetchCommits(selectedRepo);
      set({ commits, commitsLoading: false });
    } catch {
      set({ commitsLoading: false });
    }
  },

  /* ── Branches ──────────────────────────────────────────────── */
  branches: [],
  branchLoading: false,

  loadBranches: async () => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    set({ branchLoading: true });
    try {
      const data = await api.fetchBranches(selectedRepo);
      set({ branches: data.branches as BranchInfo[], branchLoading: false });
    } catch (e) {
      set({ branchLoading: false });
      toast.error("Failed to load branches", e instanceof Error ? e.message : undefined);
    }
  },

  switchBranch: async (branch) => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    try {
      const result = await api.checkoutBranch(selectedRepo, branch);
      if (result.auto_committed) {
        toast.success(
          "Auto-committed changes",
          `WIP commit on ${result.auto_commit_branch ?? "previous branch"} before switching to ${branch}`,
        );
      }
      toast.success("Switched branch", branch);
    } catch (e) {
      toast.error("Failed to switch branch", e instanceof Error ? e.message : undefined);
      return;
    }
    // Clear the active conversation — it belongs to the previous branch.
    // Also reset any in-progress streaming state so the input is usable on
    // the new branch (the server-side agent keeps running in its worktree).
    // Clear PR selection and review state so Review mode refreshes for the new branch.
    set({
      conversationId: null,
      activeConversation: null,
      selectedPR: null,
      activeReview: null,
      findingActions: {},
      sending: false,
      compacting: false,
      agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
    });
    try {
      const [context, repos, commits] = await Promise.all([
        api.fetchRepoContext(selectedRepo),
        api.fetchRepos(),
        api.fetchCommits(selectedRepo),
      ]);
      set({ repoContext: context, repos, commits });
    } catch { /* ignore */ }
    await get().loadBranches();
    await get().loadConversations(selectedRepo);
    // Load branch PR for the new branch and auto-select if in review mode
    api.fetchBranchPR(selectedRepo, branch).then((pr) => {
      if (pr && get().selectedRepo === selectedRepo && get().repoContext?.branch === branch) {
        set((s) => ({
          pullRequests: [...s.pullRequests.filter((p) => p.number !== pr.number), pr],
          selectedPR: s.workflow === "review" && !s.selectedPR ? pr : s.selectedPR,
        }));
      }
    }).catch(() => {});
  },

  createAndSwitchBranch: async (branch) => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    try {
      await api.createBranch(selectedRepo, branch);
      toast.success("Created branch", branch);
    } catch (e) {
      toast.error("Failed to create branch", e instanceof Error ? e.message : undefined);
      return;
    }
    // Clear active conversation — new branch starts fresh (same as switchBranch)
    set({
      conversationId: null,
      activeConversation: null,
      sending: false,
      compacting: false,
      agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
    });
    try {
      const [context, repos, commits] = await Promise.all([
        api.fetchRepoContext(selectedRepo),
        api.fetchRepos(),
        api.fetchCommits(selectedRepo),
      ]);
      set({ repoContext: context, repos, commits });
    } catch { /* ignore */ }
    await get().loadBranches();
    await get().loadConversations(selectedRepo);
  },

  deleteBranch: async (branch) => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    await api.deleteBranch(selectedRepo, branch);
    toast.success("Deleted branch", branch);
    await get().loadBranches();
  },

  syncBranch: async (baseBranch = "main") => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    try {
      const result = await api.syncBranch(selectedRepo, baseBranch);
      if (result.conflict) {
        toast.error("Rebase conflict", result.message || `Conflicts in ${result.conflict_files.length} file(s)`);
      } else if (result.up_to_date) {
        toast.info("Already up to date", result.message);
      } else {
        toast.success("Branch synced", result.message);
      }
      // Refresh context, commits, and branches
      const [context, repos, commits] = await Promise.all([
        api.fetchRepoContext(selectedRepo),
        api.fetchRepos(),
        api.fetchCommits(selectedRepo),
      ]);
      set({ repoContext: context, repos, commits });
      await get().loadBranches();
    } catch (e) {
      toast.error("Sync failed", e instanceof Error ? e.message : undefined);
    }
  },

  quickSave: async () => {
    const { selectedRepo, activeConversation } = get();
    if (!selectedRepo) return;
    // Use the last assistant message as context for a smarter commit message
    const lastAssistant = activeConversation?.messages
      ?.filter((m) => m.role === "assistant")
      .pop();
    const context = lastAssistant?.content?.slice(0, 300) || undefined;
    try {
      const result = await api.quickSave(selectedRepo, context);
      if (result.saved) {
        toast.success("Saved", result.message);
        // Refresh repo context to clear dirty state + commits
        try {
          const [context, repos, commits] = await Promise.all([
            api.fetchRepoContext(selectedRepo),
            api.fetchRepos(),
            api.fetchCommits(selectedRepo),
          ]);
          set({ repoContext: context, repos, commits });
        } catch { /* ignore */ }
      } else {
        toast.success("Nothing to save", "Working tree is clean");
      }
    } catch (e) {
      toast.error("Save failed", e instanceof Error ? e.message : undefined);
    }
  },

  /* ── GitHub ─────────────────────────────────────────────────── */
  githubRepos: [],
  githubLoading: false,

  loadGitHubRepos: async () => {
    set({ githubLoading: true });
    try {
      const githubRepos = await api.fetchGitHubRepos();
      set({ githubRepos, githubLoading: false });
    } catch (e) {
      set({ githubLoading: false });
      toast.error("Failed to load GitHub repos", e instanceof Error ? e.message : undefined);
    }
  },

  cloneRepo: async (fullName) => {
    try {
      await api.cloneGitHubRepo(fullName);
      toast.success("Cloned successfully", fullName);
      await get().loadRepos();
    } catch (e) {
      toast.error("Clone failed", e instanceof Error ? e.message : undefined);
      throw e;
    }
  },

  /* ── Pull Requests ─────────────────────────────────────────── */
  pullRequests: [],
  pullRequestsLoading: false,
  selectedPR: null,

  loadPullRequests: async () => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    set({ pullRequestsLoading: true });
    try {
      const prs = await api.fetchPullRequests(selectedRepo);
      set({ pullRequests: prs, pullRequestsLoading: false });
    } catch (e) {
      set({ pullRequestsLoading: false });
      toast.error("Failed to load PRs", e instanceof Error ? e.message : undefined);
    }
  },

  selectPR: (pr) => set({ selectedPR: pr }),

  /* ── Conversations ──────────────────────────────────────────── */
  conversations: [],
  activeConversation: null,
  conversationId: null,

  loadConversations: async (repo) => {
    try {
      // Load ALL conversations for this repo (no branch filter) so users
      // can see conversations from other branches in the sidebar.
      const conversations = await api.fetchConversations(repo);
      set({ conversations });
    } catch { /* ignore */ }
  },

  selectConversation: async (id) => {
    try {
      const detail = await api.fetchConversation(id);
      // Clear stale stream state from the previous conversation
      set({
        activeConversation: detail,
        conversationId: detail.id,
        sending: false,
        abortStream: null,
        streamingText: "",
        streamingProgress: null,
        agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
      });
      // If this conversation isn't in the sidebar list, refresh it
      const { conversations, selectedRepo } = get();
      if (!conversations.some((c) => c.id === detail.id)) {
        get().loadConversations(selectedRepo ?? detail.repo);
      }
      // If the target conversation has a running agent, re-subscribe to its
      // event stream so the UI resumes showing live output immediately.
      _ensureAgentSocket();
      try {
        const sessions = await api.fetchAgentSessions();
        const running = sessions.find(
          (s) => s.conversation_id === detail.id
            && (s.status === "running" || s.status === "waiting_permission" || s.status === "starting"),
        );
        // Guard: only apply if the user is still on this conversation
        if (running && get().conversationId === detail.id) {
          _streamingConversationId = detail.id;
          _agentSocket!.subscribeAgent(detail.id);
          set({
            sending: true,
            agentStream: {
              blocks: [],
              pendingPermission: null,
              isStreaming: true,
              startedAt: Date.now(),
              statusMessage: "Reconnecting to agent…",
            },
          });
        }
      } catch { /* agent session check failed — non-critical */ }

      // Load branch PR if conversation has a branch
      if (detail.branch) {
        api.fetchBranchPR(detail.repo, detail.branch).then((pr) => {
          if (pr && get().conversationId === detail.id) {
            set((s) => ({
              pullRequests: [...s.pullRequests.filter((p) => p.number !== pr.number), pr],
            }));
          }
        }).catch(() => {});
      }
    } catch { /* ignore */ }
  },

  newConversation: () => {
    set({ conversationId: null, activeConversation: null });
  },

  deleteConversation: async (id) => {
    try {
      await api.deleteConversation(id);
    } catch (e) {
      toast.error("Failed to delete conversation", e instanceof Error ? e.message : undefined);
      return;
    }
    const { conversationId, selectedRepo } = get();
    if (conversationId === id) {
      set({ conversationId: null, activeConversation: null });
    }
    await get().loadConversations(selectedRepo ?? undefined);
  },

  /* ── Chat ────────────────────────────────────────────────────── */
  sending: false,
  sendError: null,
  lastFailedMessage: null,
  streamingText: "",
  streamingProgress: null,
  agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
  serverQueue: [],
  abortStream: null,
  loadQueue: async () => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    try {
      const items = await api.fetchQueue({ repo: selectedRepo });
      set({ serverQueue: items });
    } catch (err) {
      console.warn("Failed to load message queue:", err);
    }
  },
  cancelQueueItem: async (id) => {
    try {
      await api.cancelQueueItem(id);
      set((s) => ({ serverQueue: s.serverQueue.filter((q) => q.id !== id) }));
    } catch {
      toast.error("Failed to cancel", "Queue item may have already been processed");
    }
  },
  clearQueue: async () => {
    const { serverQueue } = get();
    const pending = serverQueue.filter((q) => q.status === "pending");
    const results = await Promise.allSettled(pending.map((q) => api.cancelQueueItem(q.id)));
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length > 0) {
      toast.warning("Some items could not be cancelled", `${failures.length} may have already started processing`);
    }
    await get().loadQueue();
  },

  syncAgentState: async () => {
    // Compare the server's live session list against the local `sending` flag.
    // Called on boot and after a WS reconnect to detect desync (e.g. a page
    // reload while the agent was mid-run, or a stale `sending=true` left over
    // from a crashed session).
    try {
      const sessions = await api.fetchAgentSessions();
      const { conversationId, sending } = get();

      // Check if server has a running agent for our current conversation
      const serverSession = sessions.find(
        (s) => s.conversation_id === conversationId,
      );

      if (serverSession && (serverSession.status === "running" || serverSession.status === "waiting_permission" || serverSession.status === "starting")) {
        // Agent is still running on the server — re-subscribe to its events.
        // The server will send an agent_snapshot with accumulated state.
        if (_agentSocket && conversationId) {
          _streamingConversationId = conversationId;
          _agentSocket.subscribeAgent(conversationId);
        }
        // Mark as sending so the UI shows the active state
        if (!sending) {
          useStore.setState({
            sending: true,
            agentStream: {
              blocks: [],
              pendingPermission: null,
              isStreaming: true,
              startedAt: Date.now(),
              statusMessage: "Reconnecting to agent…",
            },
          });
        }
      } else if (sending && !serverSession) {
        // Agent has finished while we were disconnected — clear stuck state.
        useStore.setState({
          sending: false,
          agentStream: {
            blocks: [],
            pendingPermission: null,
            isStreaming: false,
            startedAt: null,
            statusMessage: null,
          },
        });
        // Reload the conversation so any result that was persisted while we
        // were disconnected becomes visible.
        if (conversationId) {
          try {
            const detail = await api.fetchConversation(conversationId);
            useStore.setState({ activeConversation: detail });
          } catch { /* ignore */ }
        }
      }

      // Also refresh the queue so the badge count is accurate.
      await get().loadQueue();
    } catch { /* network unavailable — skip */ }
  },

  sendMessage: async (message) => {
    const { selectedRepo, sending, compacting, workflow, persona, conversationId, selectedModel, repoContext, memories, documents, pinnedDocumentIds, selectedPR } = get();
    if (!selectedRepo) return;

    // Queue the message server-side if the agent is busy
    if (sending || compacting) {
      try {
        // Build system prompt snapshot (same as below)
        let system = persona.systemPrompt;
        if (repoContext?.claude_md) {
          system += `\n\n## Repository Guidelines (from CLAUDE.md)\n${repoContext.claude_md}`;
        }
        if (repoContext) {
          system += `\n\n## Current Repository State\nRepo: ${selectedRepo}\nBranch: ${repoContext.branch}`;
          if (repoContext.recent_commits.length > 0) {
            system += `\nRecent commits:\n${repoContext.recent_commits.slice(0, 5).join("\n")}`;
          }
        }
        if (memories.length > 0) {
          system += `\n\n## Memory Bank (approved learnings for this repo)\n${memories.slice(0, 5).map((m) => `- ${m.content.slice(0, 300)}`).join("\n")}`;
        }
        const qPinnedDocs = documents.filter((d) => pinnedDocumentIds.includes(d.id));
        if (qPinnedDocs.length > 0) {
          system += `\n\n## Pinned Documents`;
          for (const doc of qPinnedDocs.slice(0, 5)) {
            system += `\n\n### ${doc.title} (${doc.document_type})\n${doc.content.slice(0, 5000)}`;
          }
        }

        const item = await api.enqueueMessage({
          conversation_id: conversationId,
          repo: selectedRepo,
          branch: repoContext?.branch,
          message,
          workflow,
          model: selectedModel,
          system_prompt: system,
        });
        set((s) => ({ serverQueue: [...s.serverQueue, item] }));
        toast.info("Message queued", `Will process when the agent is ready (${get().serverQueue.length} in queue)`);
      } catch {
        toast.error("Failed to queue", "Could not send message to server queue");
      }
      return;
    }

    // Auto-generate review prompt when no text is provided
    let effectiveMessage = message;
    if (!message && workflow === "review" && selectedPR) {
      const stats = selectedPR.additions != null
        ? `\n+${selectedPR.additions}/-${selectedPR.deletions} across ${selectedPR.changed_files} files`
        : "";
      effectiveMessage = `Review PR #${selectedPR.number}: ${selectedPR.title}\n${selectedPR.url}\nBranch: ${selectedPR.head_branch} → ${selectedPR.base_branch}${stats}`;

      // Fetch existing review comments for context
      try {
        const comments = await api.fetchPRReviewComments(selectedPR.url);
        if (comments.length > 0) {
          let commentSection = "\n\n## Existing reviewer comments on this PR\nAddress these alongside your own findings:\n";
          for (const c of comments.slice(0, 30)) {
            if (c.type === "inline" && c.path) {
              commentSection += `\n- **${c.user}** on \`${c.path}${c.line ? `:${c.line}` : ""}\`:\n  ${c.body.slice(0, 500)}`;
            } else if (c.type === "review" && c.state) {
              commentSection += `\n- **${c.user}** (${c.state}):\n  ${c.body.slice(0, 500)}`;
            } else {
              commentSection += `\n- **${c.user}**:\n  ${c.body.slice(0, 500)}`;
            }
          }
          effectiveMessage += commentSection;
        }
      } catch {
        // Best-effort — don't block review if comment fetch fails
      }
    }

    set({
      sending: true,
      sendError: null,
      lastFailedMessage: null,
      streamingText: "",
      streamingProgress: null,
      agentStream: { blocks: [], pendingPermission: null, isStreaming: true, startedAt: Date.now(), statusMessage: null },
    });

    // Build system prompt: persona + repo context + relevant memories
    let system = persona.systemPrompt;

    if (repoContext?.claude_md) {
      system += `\n\n## Repository Guidelines (from CLAUDE.md)\n${repoContext.claude_md}`;
    }

    if (repoContext) {
      system += `\n\n## Current Repository State\nRepo: ${selectedRepo}\nBranch: ${repoContext.branch}`;
      if (repoContext.recent_commits.length > 0) {
        system += `\nRecent commits:\n${repoContext.recent_commits.slice(0, 5).join("\n")}`;
      }
    }

    if (memories.length > 0) {
      const relevantMemories = memories.slice(0, 5);
      system += `\n\n## Memory Bank (approved learnings for this repo)\n${relevantMemories.map((m) => `- ${m.content.slice(0, 300)}`).join("\n")}`;
    }

    // Inject pinned documents
    const pinnedDocs = documents.filter((d) => pinnedDocumentIds.includes(d.id));
    if (pinnedDocs.length > 0) {
      system += `\n\n## Pinned Documents`;
      for (const doc of pinnedDocs.slice(0, 5)) {
        system += `\n\n### ${doc.title} (${doc.document_type})\n${doc.content.slice(0, 5000)}`;
      }
    }

    // Optimistic UI: append user message immediately
    const optimisticMsg: ConversationMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: effectiveMessage,
      timestamp: new Date().toISOString(),
    };

    set((s) => {
      const activeConversation = s.activeConversation
        ? { ...s.activeConversation, messages: [...s.activeConversation.messages, optimisticMsg] }
        : {
            id: "pending",
            repo: selectedRepo,
            title: effectiveMessage.slice(0, 80),
            messages: [optimisticMsg],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            branch: repoContext?.branch ?? null,
            branches: [],
          };
      // Optimistic sidebar: bump message_count for the active conversation
      const convoId = s.conversationId;
      const conversations = convoId
        ? s.conversations.map((c) =>
            c.id === convoId ? { ...c, message_count: c.message_count + 1, updated_at: new Date().toISOString() } : c,
          )
        : s.conversations;
      return { activeConversation, conversations };
    });

    // Use the singleton agent socket
    _ensureAgentSocket();
    const { contextFiles } = get();
    _agentSocket!.start({
      repo: selectedRepo,
      branch: repoContext?.branch ?? undefined,
      message: effectiveMessage,
      workflow,
      conversation_id: conversationId ?? undefined,
      model: selectedModel ?? undefined,
      system,
      auto_accept: get().autoAccept,
      context_files: contextFiles.length > 0 ? contextFiles : undefined,
    });
  },

  retryLastMessage: () => {
    const { lastFailedMessage } = get();
    if (lastFailedMessage) {
      set({ sendError: null, lastFailedMessage: null });
      get().sendMessage(lastFailedMessage);
    }
  },

  sendAgentInput: (text) => {
    _ensureAgentSocket();
    _agentSocket!.sendInput(text);
    set({ sending: true, agentStream: { blocks: [], pendingPermission: null, isStreaming: true, startedAt: Date.now(), statusMessage: null } });
  },

  pokeAgent: () => {
    _ensureAgentSocket();
    _agentSocket!.sendInput("continue");
    toast.info("Poked the agent", "Sent a nudge to continue");
  },

  respondToPermission: (allow) => {
    _ensureAgentSocket();
    _agentSocket!.respondToPermission(allow);
    set((s) => ({
      agentStream: { ...s.agentStream, pendingPermission: null },
    }));
  },

  interruptAgent: () => {
    _agentSocket?.interrupt();
    set({
      sending: false,
      compacting: false,
      agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
    });
  },

  /* ── Workflow + Persona ──────────────────────────────────────── */
  workflow: "prompt",
  setWorkflow: (w) => {
    const updates: Partial<Store> = {
      workflow: w,
      sendError: null,
      lastFailedMessage: null,
    };
    const { persona, _preReviewPersona } = get();
    if (w === "review") {
      // Auto-switch to Reviewer persona, remembering the current one
      const reviewer = getPersonaById("reviewer");
      if (reviewer && persona.id !== "reviewer") {
        updates.persona = reviewer;
        updates._preReviewPersona = persona;
      }
    } else if (_preReviewPersona && persona.id === "reviewer") {
      // Restore previous persona when leaving review mode
      updates.persona = _preReviewPersona;
      updates._preReviewPersona = undefined;
    }
    set(updates);
  },
  autoAccept: true,
  setAutoAccept: (v) => set({ autoAccept: v }),
  persona: defaultPersona,
  setPersona: (p) => set({ persona: p }),

  /* ── Providers ───────────────────────────────────────────────── */
  providers: {},
  selectedProvider: null,
  selectedModel: null,

  loadProviders: async () => {
    // No-op — provider layer removed; Agent SDK uses OAuth CLI auth
  },

  setProvider: (p) => set({ selectedProvider: p, selectedModel: null }),
  setModel: (m) => set({ selectedModel: m }),

  /* ── Claude Auth ──────────────────────────────────────────────── */
  claudeAuth: { authenticated: false, loading: true },
  claudeAuthSubmitting: false,

  checkClaudeAuth: async () => {
    set({ claudeAuth: { ...get().claudeAuth, loading: true } });
    try {
      const result = await api.fetchClaudeAuthStatus();
      set({ claudeAuth: { authenticated: result.authenticated, message: result.message, loading: false } });
    } catch {
      set({ claudeAuth: { authenticated: false, message: "Failed to check", loading: false } });
    }
  },

  submitClaudeToken: async (token) => {
    set({ claudeAuthSubmitting: true });
    try {
      const result = await api.submitClaudeToken(token);
      if (result.success) {
        set({
          claudeAuth: { authenticated: true, message: result.message, loading: false },
          claudeAuthSubmitting: false,
        });
        toast.success("Claude connected");
        return true;
      } else {
        toast.error("Auth failed", result.error ?? "Invalid token");
        set({ claudeAuthSubmitting: false });
        return false;
      }
    } catch (e) {
      toast.error("Auth failed", e instanceof Error ? e.message : undefined);
      set({ claudeAuthSubmitting: false });
      return false;
    }
  },

  claudeLogout: async () => {
    try {
      await api.claudeLogout();
      set({ claudeAuth: { authenticated: false, loading: false } });
      toast.success("Logged out of Claude");
    } catch (e) {
      toast.error("Logout failed", e instanceof Error ? e.message : undefined);
    }
  },

  /* ── Memory Bank ─────────────────────────────────────────────── */
  memories: [],
  memoryDistillingId: null,
  messageFeedback: {},

  /* ── Memory Suggestions ──────────────────────────────────────── */
  suggestedMemories: [],
  suggestingMemories: false,
  suggestMemoriesOpen: false,
  setSuggestMemoriesOpen: (open) => set({ suggestMemoriesOpen: open }),

  loadMemories: async (repo) => {
    try {
      const memories = await api.fetchMemories(repo);
      set({ memories });
    } catch { /* ignore */ }
  },

  thumbsUp: async (messageId, content, prompt) => {
    const { selectedRepo, conversationId } = get();
    if (!selectedRepo) return;
    set({ memoryDistillingId: messageId });
    // Record feedback for analytics
    try {
      await api.saveFeedback({
        message_id: messageId,
        conversation_id: conversationId ?? undefined,
        kind: "thumbs_up",
        repo: selectedRepo,
        content: content.slice(0, 500),
        prompt: prompt.slice(0, 500),
      });
      set((s) => ({
        messageFeedback: { ...s.messageFeedback, [messageId]: "thumbs_up" as const },
      }));
    } catch { /* ignore feedback failure */ }
    // Send the prompt+response through the suggest flow so the user
    // can approve individual memories instead of saving a raw blob.
    const msgs: { role: string; content: string }[] = [];
    if (prompt) msgs.push({ role: "user", content: prompt.slice(0, 3000) });
    msgs.push({ role: "assistant", content: content.slice(0, 3000) });
    set({ suggestingMemories: true, suggestedMemories: [], suggestMemoriesOpen: true });
    try {
      const res = await api.suggestMemories({ repo: selectedRepo, messages: msgs });
      set({ memoryDistillingId: null, suggestingMemories: false });
      if (res.suggestions.length === 0) {
        toast.info("No suggestions", "No memorable patterns found in this response");
        set({ suggestMemoriesOpen: false });
        return;
      }
      set({ suggestedMemories: withIds(res.suggestions) });
    } catch (e) {
      set({ memoryDistillingId: null, suggestingMemories: false, suggestMemoriesOpen: false });
      toast.error("Failed to suggest memories", e instanceof Error ? e.message : "Please try again");
    }
  },

  deleteMemory: async (id) => {
    try {
      await api.deleteMemory(id);
      set((s) => ({ memories: s.memories.filter((m) => m.id !== id) }));
    } catch (e) {
      toast.error("Failed to delete memory", e instanceof Error ? e.message : undefined);
    }
  },

  fetchMemorySuggestions: async () => {
    const { selectedRepo, activeConversation } = get();
    if (!selectedRepo || !activeConversation?.messages?.length) {
      toast.error("No conversation", "Start a conversation first to suggest memories");
      return;
    }
    set({ suggestingMemories: true, suggestedMemories: [], suggestMemoriesOpen: true });
    try {
      const msgs = activeConversation.messages.slice(-20).map((m) => ({
        role: m.role,
        content: m.content.slice(0, 3000),
      }));
      const res = await api.suggestMemories({ repo: selectedRepo, messages: msgs });
      if (res.suggestions.length === 0) {
        toast.info("No suggestions", "No memorable patterns found in this conversation");
        set({ suggestingMemories: false, suggestMemoriesOpen: false });
        return;
      }
      set({ suggestedMemories: withIds(res.suggestions), suggestingMemories: false });
    } catch (e) {
      set({ suggestingMemories: false, suggestMemoriesOpen: false });
      toast.error("Failed to suggest memories", e instanceof Error ? e.message : "Please try again");
    }
  },

  approveMemorySuggestion: async (index) => {
    const { selectedRepo, suggestedMemories } = get();
    if (!selectedRepo) return;
    const suggestion = suggestedMemories[index];
    if (!suggestion) return;
    try {
      const entry = await api.saveMemory({
        repo: selectedRepo,
        content: suggestion.content,
        source_message_id: "",
        source_prompt: "",
        tags: suggestion.tags,
        skip_distill: true,
      });
      set((s) => ({
        memories: [...s.memories, entry],
        suggestedMemories: s.suggestedMemories.filter((_, i) => i !== index),
      }));
      toast.success("Memory saved");
    } catch (e) {
      toast.error("Failed to save", e instanceof Error ? e.message : undefined);
    }
  },

  dismissMemorySuggestion: (index) => {
    set((s) => ({
      suggestedMemories: s.suggestedMemories.filter((_, i) => i !== index),
    }));
  },

  /* ── Documents ─────────────────────────────────────────────── */
  documents: [],
  documentsLoading: false,
  pinnedDocumentIds: [],

  loadDocuments: async (repo) => {
    set({ documentsLoading: true });
    try {
      const documents = await api.fetchDocuments(repo);
      const validIds = new Set(documents.map((d) => d.id));
      set((s) => ({
        documents,
        documentsLoading: false,
        pinnedDocumentIds: s.pinnedDocumentIds.filter((id) => validIds.has(id)),
      }));
    } catch {
      set({ documentsLoading: false });
    }
  },

  createDocument: async (title, content, documentType) => {
    const { selectedRepo, conversationId } = get();
    if (!selectedRepo) return null;
    try {
      const doc = await api.createDocument({
        repo: selectedRepo,
        title,
        content,
        document_type: documentType,
        source_conversation_id: conversationId,
      });
      set((s) => ({ documents: [doc, ...s.documents] }));
      toast.success("Document saved", doc.title);
      return doc;
    } catch (e) {
      toast.error("Failed to save document", e instanceof Error ? e.message : undefined);
      return null;
    }
  },

  updateDocument: async (id, updates) => {
    try {
      const doc = await api.updateDocument(id, updates);
      set((s) => ({ documents: s.documents.map((d) => d.id === id ? doc : d) }));
    } catch (e) {
      toast.error("Failed to update document", e instanceof Error ? e.message : undefined);
    }
  },

  deleteDocument: async (id) => {
    try {
      await api.deleteDocument(id);
      set((s) => ({
        documents: s.documents.filter((d) => d.id !== id),
        pinnedDocumentIds: s.pinnedDocumentIds.filter((pid) => pid !== id),
      }));
    } catch (e) {
      toast.error("Failed to delete document", e instanceof Error ? e.message : undefined);
    }
  },

  pinDocument: (id) => set((s) => ({
    pinnedDocumentIds: s.pinnedDocumentIds.includes(id) ? s.pinnedDocumentIds : [...s.pinnedDocumentIds, id],
  })),

  unpinDocument: (id) => set((s) => ({
    pinnedDocumentIds: s.pinnedDocumentIds.filter((pid) => pid !== id),
  })),

  /* ── Review Actions ─────────────────────────────────────────── */
  activeReview: null,
  findingActions: {},
  reviewPosting: false,
  reviewApplying: false,

  setActiveReview: (review) => {
    if (review) {
      const actions: Record<string, FindingAction> = {};
      for (const f of review.findings) {
        actions[f.id] = "pending";
      }
      set({ activeReview: review, findingActions: actions });
    } else {
      set({ activeReview: null, findingActions: {} });
    }
  },

  setFindingAction: (findingId, action) =>
    set((s) => ({
      findingActions: { ...s.findingActions, [findingId]: action },
    })),

  bulkSetFindingAction: (action) =>
    set((s) => {
      const updated: Record<string, FindingAction> = {};
      for (const key of Object.keys(s.findingActions)) {
        updated[key] = action;
      }
      return { findingActions: updated };
    }),

  postReviewToGitHub: async () => {
    const { activeReview, findingActions, selectedPR } = get();
    if (!activeReview || !selectedPR) return;

    const accepted = activeReview.findings.filter(
      (f) => findingActions[f.id] === "accepted",
    );

    set({ reviewPosting: true });
    try {
      const result = await api.postReviewToGitHub({
        pr_url: selectedPR.url,
        summary: activeReview.summary,
        verdict: activeReview.verdict,
        findings: accepted,
      });
      toast.success("Review posted to GitHub", result.html_url ? `View at ${result.html_url}` : undefined);
    } catch (e) {
      toast.error("Failed to post review", e instanceof Error ? e.message : undefined);
    } finally {
      set({ reviewPosting: false });
    }
  },

  applySuggestions: async () => {
    const { activeReview, findingActions, selectedPR } = get();
    if (!activeReview || !selectedPR) return null;

    const accepted = activeReview.findings.filter(
      (f) =>
        findingActions[f.id] === "accepted" &&
        f.suggested_code != null &&
        f.original_code != null,
    );

    if (accepted.length === 0) {
      toast.warning("No accepted suggestions with code changes to apply");
      return null;
    }

    set({ reviewApplying: true });
    try {
      const result = await api.applySuggestions({
        pr_url: selectedPR.url,
        findings: accepted,
      });
      let detail = `${result.applied.length} applied — ${result.commit_sha.slice(0, 7)}`;
      if (result.skipped.length > 0) {
        detail += ` (${result.skipped.length} skipped: ${result.skipped.slice(0, 2).join(", ")})`;
      }
      toast.success("Suggestions applied", detail);
      return result;
    } catch (e) {
      toast.error("Failed to apply suggestions", e instanceof Error ? e.message : undefined);
      return null;
    } finally {
      set({ reviewApplying: false });
    }
  },

  /* ── Theme ──────────────────────────────────────────────────── */
  theme: defaultTheme,
  setTheme: (t) => {
    applyTheme(t);
    set({ theme: t });
  },

  /* ── Superlaser ───────────────────────────────────────────────── */
  superlaserFiring: false,
  compacting: false,
  fireSuperlaser: () => {
    const { conversationId, sending, compacting } = get();
    if (!conversationId) {
      toast.warning("No conversation", "Start a conversation first to compact context");
      return;
    }
    if (sending || compacting) {
      toast.warning("Agent busy", "Wait for the current response to finish");
      return;
    }
    set({ superlaserFiring: true, compacting: true });
    _ensureAgentSocket();
    _agentSocket!.compact();
  },
  stopSuperlaser: () => set({ superlaserFiring: false }),

  /* ── Context Files ────────────────────────────────────────────── */
  contextFiles: [],
  pinFile: (path) => set((s) => ({
    contextFiles: s.contextFiles.includes(path) ? s.contextFiles : [...s.contextFiles, path],
  })),
  unpinFile: (path) => set((s) => ({
    contextFiles: s.contextFiles.filter((f) => f !== path),
  })),
  clearContextFiles: () => set({ contextFiles: [] }),

  /* ── Draft Input ─────────────────────────────────────────────── */
  draftInput: "",
  setDraftInput: (text) => set({ draftInput: text }),

  /* ── Preview Deployments ────────────────────────────────────── */
  previews: [],
  previewsLoading: false,
  previewProvidersConfigured: {},

  loadPreviews: async () => {
    const repo = get().selectedRepo;
    if (!repo) return;
    set({ previewsLoading: true });
    try {
      const previews = await api.fetchPreviews(repo);
      set({ previews, previewsLoading: false });
    } catch {
      set({ previewsLoading: false });
    }
  },

  loadPreviewProviders: async () => {
    try {
      const data = await api.fetchPreviewProviders();
      set({ previewProvidersConfigured: data.providers });
    } catch {
      // Not critical — button will just be hidden
    }
  },

  createPreview: async () => {
    const { selectedRepo, repoContext } = get();
    if (!selectedRepo || !repoContext) return;
    try {
      const preview = await api.createPreview(selectedRepo, repoContext.branch);
      set((s) => ({ previews: [preview, ...s.previews] }));
      toast.success("Preview deployment started");
    } catch (e) {
      toast.error(e instanceof api.ApiError ? e.message : "Failed to create preview");
    }
  },

  deletePreview: async (id: string) => {
    const repo = get().selectedRepo;
    if (!repo) return;
    try {
      await api.deletePreview(repo, id);
      set((s) => ({
        previews: s.previews.filter((p) => p.id !== id),
      }));
      toast.success("Preview torn down");
    } catch (e) {
      toast.error(e instanceof api.ApiError ? e.message : "Failed to delete preview");
    }
  },

  refreshPreview: async (id: string) => {
    const repo = get().selectedRepo;
    if (!repo) return;
    try {
      const updated = await api.fetchPreview(repo, id);
      set((s) => ({
        previews: s.previews.map((p) => (p.id === id ? updated : p)),
      }));
    } catch {
      // Silently ignore — will retry on next poll
    }
  },

  /* ── UI State ────────────────────────────────────────────────── */
  sidebarOpen: false,
  sidebarView: "conversations",
  rightPanelOpen: false,
  rightPanelView: "files",
  settingsOpen: false,
  terminalOpen: false,

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarView: (v) => set({ sidebarView: v, sidebarOpen: true }),
  toggleRightPanel: () => set((s) => ({ rightPanelOpen: !s.rightPanelOpen })),
  setRightPanelView: (v) => set({ rightPanelView: v, rightPanelOpen: true }),
  toggleSettings: () => set((s) => ({ settingsOpen: !s.settingsOpen })),
  toggleTerminal: () => set((s) => ({ terminalOpen: !s.terminalOpen })),
  closeTerminal: () => set({ terminalOpen: false }),
}), {
  name: "deathstar-store",
  partialize: (state) => ({
    // Only persist UI preferences — repo/conversation live in the URL
    workflow: state.workflow,
    autoAccept: state.autoAccept,
    persona: state.persona,
    selectedProvider: state.selectedProvider,
    selectedModel: state.selectedModel,
    sidebarOpen: state.sidebarOpen,
    sidebarView: state.sidebarView,
    rightPanelOpen: state.rightPanelOpen,
    rightPanelView: state.rightPanelView,
    terminalOpen: state.terminalOpen,
    theme: state.theme,
  }),
}));


// ---------------------------------------------------------------------------
// Agent WebSocket singleton — created lazily, wired into the store
// ---------------------------------------------------------------------------

let _agentSocket: AgentSocket | null = null;
/** The conversation currently receiving streamed events. */
let _streamingConversationId: string | null = null;

/**
 * Returns true if stream events should be rendered in the UI.
 * When _streamingConversationId is null (before onStarted fires),
 * we allow events through to avoid dropping the first delta.
 */
function _isStreamForCurrentConversation(): boolean {
  if (!_streamingConversationId) return true;
  const current = useStore.getState().conversationId;
  return current === _streamingConversationId;
}

function _ensureAgentSocket(): void {
  if (_agentSocket) return;

  _agentSocket = new AgentSocket({
    onTextDelta: (text) => {
      if (!_isStreamForCurrentConversation()) return;
      const s = useStore.getState();
      const blocks = [...s.agentStream.blocks];
      const last = blocks[blocks.length - 1];
      if (last && last.type === "text") {
        blocks[blocks.length - 1] = { type: "text", text: last.text + text };
      } else {
        blocks.push({ type: "text", text });
      }
      useStore.setState({
        streamingText: s.streamingText + text,
        agentStream: { ...s.agentStream, blocks, statusMessage: null },
      });
    },

    onThinking: (text) => {
      if (!_isStreamForCurrentConversation()) return;
      const s = useStore.getState();
      const blocks = [...s.agentStream.blocks, { type: "thinking" as const, text }];
      useStore.setState({ agentStream: { ...s.agentStream, blocks } });
    },

    onThinkingDelta: (text) => {
      if (!_isStreamForCurrentConversation()) return;
      const s = useStore.getState();
      const blocks = [...s.agentStream.blocks];
      const last = blocks[blocks.length - 1];
      if (last && last.type === "thinking") {
        blocks[blocks.length - 1] = { type: "thinking", text: last.text + text };
      } else {
        blocks.push({ type: "thinking", text });
      }
      useStore.setState({ agentStream: { ...s.agentStream, blocks } });
    },

    onToolUse: (id, tool, input) => {
      if (!_isStreamForCurrentConversation()) return;
      const s = useStore.getState();
      const blocks = [...s.agentStream.blocks, { type: "tool_use" as const, id, tool, input }];
      useStore.setState({
        streamingProgress: `Using ${tool}...`,
        agentStream: { ...s.agentStream, blocks },
      });
    },

    onToolResult: (toolUseId, content, isError) => {
      if (!_isStreamForCurrentConversation()) return;
      const s = useStore.getState();
      const blocks = [...s.agentStream.blocks, { type: "tool_result" as const, toolUseId, content, isError }];
      useStore.setState({
        streamingProgress: null,
        agentStream: { ...s.agentStream, blocks },
      });
    },

    onPermissionRequest: (tool, input) => {
      if (!_isStreamForCurrentConversation()) return;
      useStore.setState((s) => ({
        agentStream: {
          ...s.agentStream,
          pendingPermission: { tool, input },
          blocks: [...s.agentStream.blocks, { type: "permission_request" as const, tool, input }],
        },
      }));
    },

    onStarted: (conversationId) => {
      _streamingConversationId = conversationId;
      // Only set conversationId if the user hasn't navigated away already
      const current = useStore.getState().conversationId;
      if (!current || current === conversationId) {
        useStore.setState({ conversationId });
      }
      // Refresh sidebar so the new conversation (and its message count)
      // appears immediately — the user message is already persisted at this point.
      const repo = useStore.getState().selectedRepo;
      useStore.getState().loadConversations(repo ?? undefined);
    },

    onResult: (data: AgentResult) => {
      const forCurrentConvo = _isStreamForCurrentConversation();
      _streamingConversationId = null;
      const s = useStore.getState();
      // Capture agent blocks (thinking, tool calls, etc.) for history display
      const blocks = forCurrentConvo && s.agentStream.blocks.length > 0 ? s.agentStream.blocks : undefined;
      const assistantMsg: ConversationMessage = {
        id: data.message_id,
        role: "assistant",
        content: data.content ?? "",
        timestamp: new Date().toISOString(),
        workflow: s.workflow,
        provider: "anthropic",
        model: data.model,
        duration_ms: data.duration_ms,
        usage: data.usage,
        agent_blocks: blocks,
      };

      useStore.setState((prev) => ({
        agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
        // Only update conversation-specific UI state if the result is for the conversation being viewed.
        // Otherwise a background result would clear sending/streaming state for an active send on another conversation.
        ...(forCurrentConvo ? {
          sending: false,
          streamingText: "",
          streamingProgress: null,
          abortStream: null,
          conversationId: data.conversation_id,
          activeConversation: prev.activeConversation
            ? { ...prev.activeConversation, id: data.conversation_id, messages: [...prev.activeConversation.messages, assistantMsg] }
            : null,
        } : {}),
      }));

      useStore.getState().loadConversations(s.selectedRepo ?? undefined);

      // Auto-save structured plans as documents when the plan workflow returns valid JSON.
      // This runs after the message is appended so the user sees it rendered immediately,
      // then the document is created in the background (createDocument shows its own toast).
      if (s.workflow === "plan" && assistantMsg.content) {
        const plan = tryParsePlan(assistantMsg.content);
        if (plan) {
          const md = planToMarkdown(plan);
          useStore.getState().createDocument(plan.title, md, "plan");
        } else {
          // The agent was in plan mode but didn't return parseable structured JSON.
          // This is expected for the first response (prose plan) — only warn if
          // the content looks like it was attempting JSON (starts with { or [).
          const trimmed = assistantMsg.content.trim();
          const looksLikeJSON = trimmed.startsWith("{") || trimmed.startsWith("[") ||
            (trimmed.startsWith("```") && trimmed.includes("{"));
          if (looksLikeJSON) {
            toast.persistent("error", "Plan not saved",
              "The response looked like JSON but couldn't be parsed as a structured plan.",
              { label: "Retry", onClick: () => useStore.getState().sendMessage(RETRY_STRUCTURE_PLAN_PROMPT) },
            );
          }
        }
      }

      // Always refresh repo state after agent completes — the agent may have
      // written files, committed, switched branches, etc.  The old heuristic
      // only refreshed when it detected Write/Edit/Bash tool uses, which missed
      // cases like "agent committed everything" (dirty→clean) or indirect writes
      // via Bash, leaving the Save button out of sync.
      if (s.selectedRepo) {
        Promise.all([
          api.fetchRepoContext(s.selectedRepo),
          api.fetchRepos(),
          api.fetchCommits(s.selectedRepo),
        ]).then(([context, repos, commits]) => {
          useStore.setState({ repoContext: context, repos, commits });
          if (context.branch_switched_from) {
            toast.info(
              "Branch cleaned up",
              `"${context.branch_switched_from}" was deleted on remote (PR merged?). Switched to ${context.branch}.`,
            );
            useStore.getState().loadBranches();
          }
          // Only show "changes applied" toast if the agent actually used write tools
          const writeTools = new Set(["Write", "Edit", "Bash"]);
          const madeChanges = blocks?.some(
            (b) => b.type === "tool_use" && writeTools.has((b as { tool?: string }).tool ?? ""),
          );
          if (madeChanges && !context.branch_switched_from) {
            toast.success("Branch updated", `Changes applied to ${context.branch}`);
          }
          // Refresh branch PR — the agent may have created or updated a PR
          // (e.g. via "Make PR" button or gh pr create in Bash). Without this
          // the new PR won't appear in the UI until the user navigates away.
          const repo = useStore.getState().selectedRepo;
          if (repo && context.branch) {
            api.fetchBranchPR(repo, context.branch).then((pr) => {
              if (pr && useStore.getState().selectedRepo === repo) {
                useStore.setState((prev) => ({
                  pullRequests: [...prev.pullRequests.filter((p) => p.number !== pr.number), pr],
                }));
              }
            }).catch(() => {});
          }
        }).catch(() => { /* ignore */ });
      }

      // Refresh server queue
      setTimeout(() => useStore.getState().loadQueue(), 100);
    },

    onError: (code, message) => {
      const forCurrentConvo = _isStreamForCurrentConversation();
      _streamingConversationId = null;

      // Always clear agent stream blocks
      useStore.setState({
        agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
      });

      if (forCurrentConvo) {
        // Find the last user message so we can offer retry
        const conv = useStore.getState().activeConversation;
        const lastUserMsg = conv?.messages
          ?.filter((m) => m.role === "user")
          .at(-1)?.content ?? null;

        // Remove the optimistic user message that failed
        const cleaned = conv
          ? { ...conv, messages: conv.messages.filter((m) => !(m.role === "user" && m.id.startsWith("pending-") && m.content === lastUserMsg)) }
          : null;

        useStore.setState({
          sending: false,
          sendError: message,
          lastFailedMessage: lastUserMsg,
          streamingText: "",
          streamingProgress: null,
          abortStream: null,
          activeConversation: cleaned,
        });
      }

      if (code === "AUTH_REQUIRED" || code === "AUTH_EXPIRED") {
        // Refresh auth state so the Claude indicator turns red
        useStore.getState().checkClaudeAuth();
        toast.error(
          "Claude authentication required",
          "Click the Claude icon in the top bar to connect your account.",
        );
      } else {
        toast.error("Agent error", message);
      }
    },

    onStatus: (event: AgentStatusEvent) => {
      if (!_isStreamForCurrentConversation()) return;
      useStore.setState((s) => ({
        agentStream: { ...s.agentStream, statusMessage: event.message },
      }));
    },

    onCompactDone: (summary) => {
      if (!_isStreamForCurrentConversation()) return;
      const COMPACTOR_QUOTES = [
        "One thing's for sure — we're all going to be a lot thinner.",
        "Shut down all the garbage mashers on the detention level!",
        "The walls are moving!",
        "Try bracing it with something.",
        "Get on top of it!",
        "I've got a bad feeling about this.",
        "Threepio! Come in, Threepio! Where could he be?",
        "Garbage chute… really wonderful idea.",
        "What an incredible smell you've discovered!",
        "It could be worse… it's worse.",
      ];
      const quote = COMPACTOR_QUOTES[Math.floor(Math.random() * COMPACTOR_QUOTES.length)];

      toast.success("Trash Compactor Complete", `"${quote}"`);

      // Insert a compactor divider message into the conversation
      const compactorMsg: ConversationMessage = {
        id: `compactor-${Date.now()}`,
        role: "assistant",
        content: `--- \n\n**🗑️ Trash Compactor Activated**\n\n*"${quote}"*\n\nPrevious context has been compressed. The conversation continues with a summarized history.\n\n${summary ? `**Summary:** ${summary}` : ""}\n\n---`,
        timestamp: new Date().toISOString(),
      };

      useStore.setState((prev) => ({
        compacting: false,
        activeConversation: prev.activeConversation
          ? {
              ...prev.activeConversation,
              messages: [...prev.activeConversation.messages, compactorMsg],
            }
          : null,
      }));

      // Refresh server queue
      setTimeout(() => useStore.getState().loadQueue(), 100);
    },

    onPRCreated: (data) => {
      const pr: PullRequestSummary = {
        number: data.pr_number,
        title: data.pr_title,
        url: data.pr_url,
        head_branch: data.branch,
        base_branch: data.base_branch,
        draft: data.draft,
        state: "open",
        user: data.user || "",
        updated_at: new Date().toISOString(),
        additions: null,
        deletions: null,
        changed_files: null,
        mergeable: null,
        mergeable_state: null,
      };
      useStore.setState((s) => ({
        pullRequests: [...s.pullRequests.filter((p) => p.number !== pr.number), pr],
      }));
    },

    onRepoEvent: (event: RepoEventData) => {
      const s = useStore.getState();
      if (!s.selectedRepo || event.repo !== s.selectedRepo) return;

      const refreshContext = () =>
        api.fetchRepoContext(event.repo).then((ctx) => {
          useStore.setState({ repoContext: ctx });
          if (ctx.branch_switched_from) {
            toast.info(
              "Branch cleaned up",
              `"${ctx.branch_switched_from}" was deleted on remote (PR merged?). Switched to ${ctx.branch}.`,
            );
            useStore.getState().loadBranches();
          }
        }).catch(() => {});
      const refreshCommits = () =>
        api.fetchCommits(event.repo).then((c) => useStore.setState({ commits: c })).catch(() => {});
      const refreshBranches = () => useStore.getState().loadBranches();
      const refreshPRs = () =>
        api.fetchPullRequests(event.repo).then((prs) => useStore.setState({ pullRequests: prs })).catch(() => {});
      const refreshRepos = () =>
        api.fetchRepos().then((r) => useStore.setState({ repos: r })).catch(() => {});

      switch (event.event_type) {
        case "push": {
          const sender = (event.data.sender as string) || "Someone";
          const ref = (event.data.ref as string) || "";
          const branch = ref.replace("refs/heads/", "");
          const currentBranch = s.repoContext?.branch;

          // If we're already on the pushed branch, this is most likely our
          // own push (from the agent or terminal).  No need to show a "Sync
          // now" toast — just silently refresh context so the UI stays fresh.
          if (currentBranch && branch === currentBranch) {
            void Promise.all([refreshContext(), refreshCommits()]);
            break;
          }

          const commitCount = Array.isArray(event.data.commits) ? event.data.commits.length : 0;
          const desc = commitCount > 0
            ? `${sender} pushed ${commitCount} commit${commitCount > 1 ? "s" : ""} to ${branch}`
            : `${sender} pushed to ${branch}`;
          toast.persistent("info", "Branch updated", desc, {
            label: "Sync now",
            onClick: () => useStore.getState().syncBranch(),
          });
          void Promise.all([refreshContext(), refreshCommits(), refreshBranches()]);
          break;
        }
        case "pr_update":
          toast.info("PR updated", `#${event.data.number} ${event.data.title}`);
          refreshPRs();
          // A merged PR may delete the branch — refresh context to detect and auto-switch
          refreshContext();
          refreshBranches();
          break;
        case "ci_status":
          toast.info("CI status", `${event.data.context}: ${event.data.state}`);
          break;
        case "local_commit":
          refreshCommits();
          refreshContext();
          refreshRepos();
          break;
        case "local_checkout": {
          const fromBranch = (event.data.from_branch as string) || "unknown";
          const toBranch = (event.data.to_branch as string) || "unknown";
          // Inject a system note into the active conversation so the agent
          // knows the branch changed when it builds the next prompt
          if (s.activeConversation && fromBranch !== toBranch) {
            const note: ConversationMessage = {
              id: `branch-switch-${Date.now()}`,
              role: "user",
              content: `[Branch switched from \`${fromBranch}\` to \`${toBranch}\`]`,
              timestamp: new Date().toISOString(),
            };
            useStore.setState((prev) => ({
              activeConversation: prev.activeConversation
                ? { ...prev.activeConversation, messages: [...prev.activeConversation.messages, note] }
                : null,
            }));
          }
          refreshContext();
          refreshBranches();
          refreshCommits();
          break;
        }
        case "branch_update":
          refreshBranches();
          break;
        case "repo_dirty":
          refreshRepos();
          break;
        case "queue_processing": {
          const convId = event.data.conversation_id as string;
          const queueMessage = (event.data.message as string) || "";
          const queueItemId = event.data.queue_item_id as string;

          // Refresh the queue badge (item moves from pending → processing)
          useStore.getState().loadQueue();

          // If this is for the active conversation, subscribe to the agent
          // stream so we get real-time text/tool/thinking deltas.
          if (s.conversationId === convId) {
            // Post the queued user message into the chat UI
            const queuedUserMsg: ConversationMessage = {
              id: `queued-${queueItemId}`,
              role: "user",
              content: queueMessage,
              timestamp: new Date().toISOString(),
            };
            useStore.setState((prev) => ({
              sending: true,
              streamingText: "",
              streamingProgress: null,
              agentStream: { blocks: [], pendingPermission: null, isStreaming: true, startedAt: Date.now(), statusMessage: "Processing queued message…" },
              activeConversation: prev.activeConversation
                ? { ...prev.activeConversation, messages: [...prev.activeConversation.messages, queuedUserMsg] }
                : null,
            }));

            // Subscribe to the agent's event stream for live streaming
            _ensureAgentSocket();
            _agentSocket!.subscribeAgent(convId);
          } else {
            toast.info("Processing queued message", queueMessage.slice(0, 80));
          }
          break;
        }
        case "queue_completed": {
          const convId = event.data.conversation_id as string;
          const preview = (event.data.message_preview as string) || "Queued message";
          useStore.getState().loadQueue();
          // If this conversation is active, the result event from the agent
          // subscription already updated the UI — just refresh side data.
          // Otherwise show a toast.
          if (s.conversationId !== convId) {
            toast.success("Queued message completed", preview);
          }
          // Refresh conversation if it matches the active one and we weren't
          // subscribed (e.g. user navigated to this convo after processing started)
          if (s.conversationId === convId && !s.sending) {
            api.fetchConversation(convId).then((c) => useStore.setState({ activeConversation: c })).catch(() => {});
          }
          refreshContext();
          refreshRepos();
          refreshCommits();
          break;
        }
        case "queue_failed": {
          const errorMsg = (event.data.error as string) || "Unknown error";
          toast.error("Queued message failed", errorMsg);
          useStore.getState().loadQueue();
          // Reset sending state if this was for the active conversation
          if (event.data.conversation_id === s.conversationId) {
            useStore.setState({
              sending: false,
              agentStream: { blocks: [], pendingPermission: null, isStreaming: false, startedAt: null, statusMessage: null },
            });
          }
          break;
        }
      }
    },

    onSnapshot: (snapshot) => {
      // Restore agent state from a server-side snapshot (after reconnecting
      // to a still-running agent).  Cast blocks from the server format to
      // AgentContentBlock[].

      // Track this snapshot's conversation so subsequent deltas are scoped correctly.
      if (snapshot.conversation_id) {
        _streamingConversationId = snapshot.conversation_id;
      }
      // If the user navigated away before the snapshot arrived, discard it.
      if (!_isStreamForCurrentConversation()) return;

      const blocks = (snapshot.blocks || []).map((b: Record<string, unknown>) => {
        switch (b.type) {
          case "text": return { type: "text" as const, text: b.text as string };
          case "thinking": return { type: "thinking" as const, text: b.text as string };
          case "tool_use": return { type: "tool_use" as const, id: b.id as string, tool: b.tool as string, input: b.input as Record<string, unknown> };
          case "tool_result": return { type: "tool_result" as const, toolUseId: b.toolUseId as string, content: b.content as string, isError: b.isError as boolean };
          case "permission_request": return { type: "permission_request" as const, tool: b.tool as string, input: b.input as Record<string, unknown> };
          default: return { type: "text" as const, text: "" };
        }
      });
      const isRunning = snapshot.status === "running" || snapshot.status === "waiting_permission" || snapshot.status === "starting";

      // Restore pending permission if the agent is waiting for one.
      // Look for the last permission_request block in the snapshot.
      let pendingPermission: { tool: string; input: Record<string, unknown> } | null = null;
      if (snapshot.status === "waiting_permission") {
        const permBlocks = (snapshot.blocks || []).filter(
          (b: Record<string, unknown>) => b.type === "permission_request"
        );
        if (permBlocks.length > 0) {
          const last = permBlocks[permBlocks.length - 1] as Record<string, unknown>;
          pendingPermission = {
            tool: last.tool as string,
            input: (last.input ?? {}) as Record<string, unknown>,
          };
        }
      }

      useStore.setState({
        sending: isRunning,
        streamingText: snapshot.text || "",
        agentStream: {
          blocks,
          pendingPermission,
          isStreaming: isRunning,
          startedAt: isRunning ? Date.now() : null,
          statusMessage: snapshot.status === "waiting_permission" ? "Waiting for permission…" : null,
        },
      });
    },

    onStateChange: (state) => {
      if (state === "disconnected") {
        // If the socket drops while the agent is streaming, mark the stream as
        // paused after a short grace period so the UI doesn't stay permanently
        // locked.  We wait 4 s to let the auto-reconnect succeed first — if it
        // does, `syncAgentState` on the reconnect will reconcile everything.
        // Critically we DO NOT clear agentStream.blocks so the partial output
        // the user was watching remains visible rather than vanishing.
        setTimeout(() => {
          if (_agentSocket?.state !== "connected") {
            const { sending, compacting } = useStore.getState();
            if (sending || compacting) {
              useStore.setState((s) => ({
                sending: false,
                compacting: false,
                agentStream: {
                  ...s.agentStream,
                  isStreaming: false,
                  statusMessage: "Connection lost — reconnecting…",
                },
              }));
            }
          }
        }, 4000);
      } else if (state === "connected") {
        // On every (re)connect: reconcile UI state and re-subscribe to repo
        // events (subscriptions are per-connection and don't survive a close).
        const { selectedRepo } = useStore.getState();
        useStore.getState().syncAgentState();
        if (selectedRepo && _agentSocket) {
          _agentSocket.subscribeEvents(selectedRepo);
        }
      }
    },
  });

  _agentSocket.connect();
}

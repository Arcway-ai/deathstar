import { create } from "zustand";
import * as api from "./api";
import { defaultPersona } from "./personas";
import type {
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  GitHubRepo,
  MemoryEntry,
  Persona,
  ProviderName,
  ProviderStatus,
  RepoContext,
  RepoInfo,
  SidebarView,
  WorkflowKind,
} from "./types";

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

  /* ── GitHub ────────────────────────────────────────────────── */
  githubRepos: GitHubRepo[];
  githubLoading: boolean;
  loadGitHubRepos: () => Promise<void>;
  cloneRepo: (fullName: string) => Promise<void>;

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
  sendMessage: (message: string) => Promise<void>;

  /* ── Workflow + Persona ─────────────────────────────────────── */
  workflow: WorkflowKind;
  setWorkflow: (w: WorkflowKind) => void;
  writeChanges: boolean;
  setWriteChanges: (v: boolean) => void;
  persona: Persona;
  setPersona: (p: Persona) => void;

  /* ── Providers ──────────────────────────────────────────────── */
  providers: Record<string, ProviderStatus>;
  selectedProvider: ProviderName | null;
  loadProviders: () => Promise<void>;
  setProvider: (p: ProviderName) => void;

  /* ── Memory Bank ────────────────────────────────────────────── */
  memories: MemoryEntry[];
  loadMemories: (repo?: string) => Promise<void>;
  thumbsUp: (messageId: string, content: string, prompt: string) => Promise<void>;
  deleteMemory: (id: string) => Promise<void>;

  /* ── UI State ───────────────────────────────────────────────── */
  sidebarOpen: boolean;
  sidebarView: SidebarView;
  settingsOpen: boolean;
  toggleSidebar: () => void;
  setSidebarView: (v: SidebarView) => void;
  toggleSettings: () => void;
}

export const useStore = create<Store>((set, get) => ({
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
    } catch {
      set({ repoLoading: false });
    }
  },

  selectRepo: async (name) => {
    set({ selectedRepo: name, repoContext: null, fileTree: [], fileContent: null, conversationId: null, activeConversation: null });
    try {
      const [context, conversations] = await Promise.all([
        api.fetchRepoContext(name),
        api.fetchConversations(name),
      ]);
      set({ repoContext: context, conversations });
    } catch {
      // context fetch may fail if endpoint not yet available
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

  /* ── GitHub ─────────────────────────────────────────────────── */
  githubRepos: [],
  githubLoading: false,

  loadGitHubRepos: async () => {
    set({ githubLoading: true });
    try {
      const githubRepos = await api.fetchGitHubRepos();
      set({ githubRepos, githubLoading: false });
    } catch {
      set({ githubLoading: false });
    }
  },

  cloneRepo: async (fullName) => {
    await api.cloneGitHubRepo(fullName);
    await get().loadRepos();
  },

  /* ── Conversations ──────────────────────────────────────────── */
  conversations: [],
  activeConversation: null,
  conversationId: null,

  loadConversations: async (repo) => {
    try {
      const conversations = await api.fetchConversations(repo);
      set({ conversations });
    } catch { /* ignore */ }
  },

  selectConversation: async (id) => {
    try {
      const detail = await api.fetchConversation(id);
      set({ activeConversation: detail, conversationId: detail.id });
    } catch { /* ignore */ }
  },

  newConversation: () => {
    set({ conversationId: null, activeConversation: null });
  },

  deleteConversation: async (id) => {
    await api.deleteConversation(id);
    const { conversationId, selectedRepo } = get();
    if (conversationId === id) {
      set({ conversationId: null, activeConversation: null });
    }
    await get().loadConversations(selectedRepo ?? undefined);
  },

  /* ── Chat ────────────────────────────────────────────────────── */
  sending: false,
  sendError: null,

  sendMessage: async (message) => {
    const { selectedRepo, workflow, persona, conversationId, writeChanges, selectedProvider, repoContext, memories } = get();
    if (!selectedRepo) return;

    set({ sending: true, sendError: null });

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

    // Optimistic UI: append user message immediately
    const optimisticMsg: ConversationMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    };

    set((s) => ({
      activeConversation: s.activeConversation
        ? { ...s.activeConversation, messages: [...s.activeConversation.messages, optimisticMsg] }
        : {
            id: "pending",
            repo: selectedRepo,
            title: message.slice(0, 80),
            messages: [optimisticMsg],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
    }));

    try {
      const res = await api.sendChat({
        repo: selectedRepo,
        message,
        conversation_id: conversationId ?? undefined,
        workflow,
        provider: selectedProvider ?? undefined,
        system,
        write_changes: writeChanges,
      });

      const assistantMsg: ConversationMessage = {
        id: res.message_id,
        role: "assistant",
        content: res.content ?? res.error?.message ?? "",
        timestamp: new Date().toISOString(),
        workflow: res.workflow,
        provider: res.provider,
        model: res.model,
        duration_ms: res.duration_ms,
      };

      set((s) => ({
        sending: false,
        conversationId: res.conversation_id,
        activeConversation: s.activeConversation
          ? { ...s.activeConversation, id: res.conversation_id, messages: [...s.activeConversation.messages, assistantMsg] }
          : null,
      }));

      // Refresh conversations list
      get().loadConversations(selectedRepo);
    } catch (e) {
      set({
        sending: false,
        sendError: e instanceof Error ? e.message : "unknown error",
      });
    }
  },

  /* ── Workflow + Persona ──────────────────────────────────────── */
  workflow: "prompt",
  setWorkflow: (w) => set({ workflow: w }),
  writeChanges: false,
  setWriteChanges: (v) => set({ writeChanges: v }),
  persona: defaultPersona,
  setPersona: (p) => set({ persona: p }),

  /* ── Providers ───────────────────────────────────────────────── */
  providers: {},
  selectedProvider: null,

  loadProviders: async () => {
    try {
      const providers = await api.fetchProviders();
      set({ providers });
      // Auto-select first configured provider
      const { selectedProvider } = get();
      if (!selectedProvider) {
        const configured = Object.entries(providers).find(([, v]) => v.configured);
        if (configured) {
          set({ selectedProvider: configured[0] as ProviderName });
        }
      }
    } catch { /* ignore */ }
  },

  setProvider: (p) => set({ selectedProvider: p }),

  /* ── Memory Bank ─────────────────────────────────────────────── */
  memories: [],

  loadMemories: async (repo) => {
    try {
      const memories = await api.fetchMemories(repo);
      set({ memories });
    } catch { /* ignore */ }
  },

  thumbsUp: async (messageId, content, prompt) => {
    const { selectedRepo } = get();
    if (!selectedRepo) return;
    try {
      const entry = await api.saveMemory({
        repo: selectedRepo,
        content,
        source_message_id: messageId,
        source_prompt: prompt,
        tags: [],
      });
      set((s) => ({ memories: [...s.memories, entry] }));
    } catch { /* ignore */ }
  },

  deleteMemory: async (id) => {
    await api.deleteMemory(id);
    set((s) => ({ memories: s.memories.filter((m) => m.id !== id) }));
  },

  /* ── UI State ────────────────────────────────────────────────── */
  sidebarOpen: false,
  sidebarView: "conversations",
  settingsOpen: false,

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarView: (v) => set({ sidebarView: v, sidebarOpen: true }),
  toggleSettings: () => set((s) => ({ settingsOpen: !s.settingsOpen })),
}));

import { useNavigate } from "react-router-dom";
import {
  MessageSquare,
  Brain,
  Trash2,
} from "lucide-react";
import { useStore } from "../store";
import type { SidebarView } from "../types";

const tabs: { id: SidebarView; icon: typeof MessageSquare; label: string }[] = [
  { id: "conversations", icon: MessageSquare, label: "Chats" },
  { id: "memory", icon: Brain, label: "Memory" },
];

export default function Sidebar() {
  const view = useStore((s) => s.sidebarView);
  const setSidebarView = useStore((s) => s.setSidebarView);

  // Guard against stale persisted values from old sidebar views
  const safeView: SidebarView = view === "conversations" || view === "memory" ? view : "conversations";

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-border-subtle bg-bg-primary">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border-subtle">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setSidebarView(tab.id)}
            className={`flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors ${
              safeView === tab.id
                ? "border-b-2 border-accent text-accent"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-2">
        {safeView === "conversations" && <ConversationList />}
        {safeView === "memory" && <MemoryPanel />}
      </div>
    </aside>
  );
}

function ConversationList() {
  const navigate = useNavigate();
  const conversations = useStore((s) => s.conversations);
  const conversationId = useStore((s) => s.conversationId);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const deleteConversation = useStore((s) => s.deleteConversation);

  if (conversations.length === 0) {
    return (
      <p className="px-2 py-8 text-center text-xs text-text-muted">
        No conversations yet
      </p>
    );
  }

  return (
    <div className="space-y-0.5">
      {conversations.map((c) => (
        <div
          key={c.id}
          className={`group flex items-center gap-2 rounded-md px-2 py-2 cursor-pointer transition-colors ${
            c.id === conversationId
              ? "bg-accent-muted text-accent"
              : "text-text-secondary hover:bg-bg-hover"
          }`}
          onClick={() => {
            if (selectedRepo) {
              navigate(`/${encodeURIComponent(selectedRepo)}/c/${encodeURIComponent(c.id)}`);
            }
          }}
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium">{c.title}</p>
            <p className="text-[10px] text-text-muted">
              {c.message_count} messages
            </p>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              deleteConversation(c.id);
            }}
            className="invisible flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-muted hover:bg-error/20 hover:text-error group-hover:visible"
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}

function MemoryPanel() {
  const memories = useStore((s) => s.memories);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const loadMemories = useStore((s) => s.loadMemories);
  const deleteMemory = useStore((s) => s.deleteMemory);

  if (memories.length === 0) {
    return (
      <div className="px-2 py-8 text-center">
        <Brain size={24} className="mx-auto mb-2 text-text-muted" />
        <p className="text-xs text-text-muted mb-3">
          No memories saved yet.
          <br />
          Thumbs-up a response to save it.
        </p>
        <button
          onClick={() => loadMemories(selectedRepo ?? undefined)}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-xs text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {memories.map((m) => (
        <div
          key={m.id}
          className="group rounded-md border border-border-subtle bg-bg-surface p-2"
        >
          <p className="text-xs text-text-secondary line-clamp-3">
            {m.content}
          </p>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-[10px] text-text-muted">
              {new Date(m.created_at).toLocaleDateString()}
            </span>
            <button
              onClick={() => deleteMemory(m.id)}
              className="invisible text-text-muted hover:text-error group-hover:visible"
            >
              <Trash2 size={10} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

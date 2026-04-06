import { useNavigate } from "react-router-dom";
import { useState } from "react";
import {
  MessageSquare,
  Brain,
  FileText,
  Pin,
  PinOff,
  Trash2,
  GitBranch,
} from "lucide-react";
import { useStore } from "../store";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { SidebarView } from "../types";

export default function Sidebar() {
  const view = useStore((s) => s.sidebarView);
  const setSidebarView = useStore((s) => s.setSidebarView);
  const sidebarOpen = useStore((s) => s.sidebarOpen);

  const safeView: SidebarView = view === "conversations" || view === "memory" || view === "documents" ? view : "conversations";

  return (
    <aside className={`absolute left-0 top-0 z-40 flex h-full w-72 shrink-0 flex-col border-r border-border-subtle bg-bg-primary transition-transform duration-200 md:relative md:z-auto md:translate-x-0 ${sidebarOpen ? "translate-x-0 animate-slide-left" : "-translate-x-full"}`}>
      <Tabs
        value={safeView}
        onValueChange={(v) => setSidebarView(v as SidebarView)}
        className="flex flex-1 flex-col overflow-hidden"
      >
        <TabsList variant="line" className="w-full shrink-0 rounded-none border-b border-border-subtle bg-transparent p-0">
          <TabsTrigger
            value="conversations"
            className="flex-1 gap-1.5 rounded-none py-2.5 text-xs text-text-muted data-active:text-accent data-active:after:bg-accent"
          >
            <MessageSquare size={14} />
            Chats
          </TabsTrigger>
          <TabsTrigger
            value="memory"
            className="flex-1 gap-1.5 rounded-none py-2.5 text-xs text-text-muted data-active:text-accent data-active:after:bg-accent"
          >
            <Brain size={14} />
            Memory
          </TabsTrigger>
          <TabsTrigger
            value="documents"
            className="flex-1 gap-1.5 rounded-none py-2.5 text-xs text-text-muted data-active:text-accent data-active:after:bg-accent"
          >
            <FileText size={14} />
            Docs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="conversations" className="flex-1 overflow-y-auto p-2">
          <ConversationList />
        </TabsContent>
        <TabsContent value="memory" className="flex-1 overflow-y-auto p-2">
          <MemoryPanel />
        </TabsContent>
        <TabsContent value="documents" className="flex-1 overflow-y-auto p-2">
          <DocumentsPanel />
        </TabsContent>
      </Tabs>
    </aside>
  );
}

/* ── Destructive action button ──────────────────────────────────
   Always visible (works on mobile), but very subtle until interacted with.
   Shared pattern across conversations, memories, and documents. */
function DestructiveButton({ onClick, size = 12 }: { onClick: () => void; size?: number }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-muted/40 hover:bg-error/20 hover:text-error active:bg-error/30 transition-colors"
    >
      <Trash2 size={size} />
    </button>
  );
}

function ConversationList() {
  const navigate = useNavigate();
  const conversations = useStore((s) => s.conversations);
  const conversationId = useStore((s) => s.conversationId);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const deleteConversation = useStore((s) => s.deleteConversation);
  const toggleSidebar = useStore((s) => s.toggleSidebar);

  if (conversations.length === 0) {
    return (
      <p className="px-2 py-8 text-center text-xs text-text-muted">
        No conversations yet
      </p>
    );
  }

  return (
    <div className="space-y-0.5">
      {conversations.map((c) => {
        const isActive = c.id === conversationId;
        const branches = c.branches?.length > 0 ? c.branches : (c.branch && c.branch !== "main" && c.branch !== "master" ? [c.branch] : []);
        return (
          <div
            key={c.id}
            className={`flex items-start gap-2 rounded-md px-2 py-2 cursor-pointer transition-colors ${
              isActive
                ? "bg-accent-muted text-accent"
                : "text-text-secondary hover:bg-bg-hover"
            }`}
            onClick={() => {
              if (selectedRepo) {
                navigate(`/${encodeURIComponent(selectedRepo)}/c/${encodeURIComponent(c.id)}`);
                if (window.innerWidth < 768) toggleSidebar();
              }
            }}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{c.title}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] text-text-muted">
                  {c.message_count} msg{c.message_count !== 1 ? "s" : ""}
                </span>
              </div>
              {branches.length > 0 && (
                <BranchPills branches={branches} isActive={isActive} />
              )}
            </div>
            <DestructiveButton onClick={() => deleteConversation(c.id)} />
          </div>
        );
      })}
    </div>
  );
}

const MAX_VISIBLE_BRANCHES = 2;

function BranchPills({ branches, isActive }: { branches: string[]; isActive: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? branches : branches.slice(0, MAX_VISIBLE_BRANCHES);
  const overflow = branches.length - MAX_VISIBLE_BRANCHES;

  return (
    <div className="flex flex-wrap items-center gap-1 mt-1">
      {visible.map((b) => (
        <span
          key={b}
          className={`inline-flex items-center gap-0.5 rounded-sm px-1 py-px text-[9px] font-mono leading-tight ${
            isActive
              ? "bg-accent/15 text-accent/80"
              : "bg-bg-elevated text-text-muted"
          }`}
          title={b}
        >
          <GitBranch size={7} className="shrink-0" />
          <span className="truncate max-w-[7rem]">{b}</span>
        </span>
      ))}
      {overflow > 0 && !expanded && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(true); }}
          className={`rounded-sm px-1 py-px text-[9px] font-mono leading-tight transition-colors ${
            isActive
              ? "text-accent/60 hover:text-accent"
              : "text-text-muted/60 hover:text-text-muted"
          }`}
        >
          +{overflow} more
        </button>
      )}
      {expanded && overflow > 0 && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
          className={`rounded-sm px-1 py-px text-[9px] font-mono leading-tight transition-colors ${
            isActive
              ? "text-accent/60 hover:text-accent"
              : "text-text-muted/60 hover:text-text-muted"
          }`}
        >
          show less
        </button>
      )}
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
        <Card key={m.id} size="sm" className="ring-0 rounded-md border border-border-subtle bg-bg-surface">
          <CardContent className="p-2">
            <p className="text-xs text-text-secondary line-clamp-3">
              {m.content}
            </p>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[10px] text-text-muted">
                {new Date(m.created_at).toLocaleDateString()}
              </span>
              <DestructiveButton onClick={() => deleteMemory(m.id)} size={10} />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function DocumentsPanel() {
  const documents = useStore((s) => s.documents);
  const pinnedDocumentIds = useStore((s) => s.pinnedDocumentIds);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const loadDocuments = useStore((s) => s.loadDocuments);
  const deleteDocument = useStore((s) => s.deleteDocument);
  const pinDocument = useStore((s) => s.pinDocument);
  const unpinDocument = useStore((s) => s.unpinDocument);

  if (documents.length === 0) {
    return (
      <div className="px-2 py-8 text-center">
        <FileText size={24} className="mx-auto mb-2 text-text-muted" />
        <p className="text-xs text-text-muted mb-3">
          No documents yet.
          <br />
          Generate a plan and save it as a document.
        </p>
        <button
          onClick={() => loadDocuments(selectedRepo ?? undefined)}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-xs text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {documents.map((d) => {
        const isPinned = pinnedDocumentIds.includes(d.id);
        return (
          <Card key={d.id} size="sm" className="ring-0 rounded-md border border-border-subtle bg-bg-surface">
            <CardContent className="p-2">
              <div className="flex items-center gap-1.5">
                <Badge variant="secondary" className="h-4 px-1.5 text-[9px] shrink-0">
                  {d.document_type.replace("_", " ")}
                </Badge>
                <p className="text-xs font-medium text-text-primary truncate flex-1">
                  {d.title}
                </p>
              </div>
              <p className="mt-1 text-xs text-text-secondary line-clamp-2">
                {d.content.slice(0, 200)}
              </p>
              <div className="mt-1 flex items-center justify-between">
                <span className="text-[10px] text-text-muted">
                  {new Date(d.updated_at).toLocaleDateString()}
                </span>
                <div className="flex items-center gap-0.5">
                  <button
                    onClick={(e) => { e.stopPropagation(); isPinned ? unpinDocument(d.id) : pinDocument(d.id); }}
                    className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                      isPinned
                        ? "text-accent hover:text-accent-hover"
                        : "text-text-muted/40 hover:text-accent"
                    }`}
                    title={isPinned ? "Unpin from context" : "Pin to context"}
                  >
                    {isPinned ? <PinOff size={10} /> : <Pin size={10} />}
                  </button>
                  <DestructiveButton onClick={() => deleteDocument(d.id)} size={10} />
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

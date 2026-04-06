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
        const branches = c.branches?.length > 0 ? c.branches : (c.branch && c.branch !== "main" && c.branch !== "master" ? [c.branch] : []);
        return (
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
                if (window.innerWidth < 768) toggleSidebar();
              }
            }}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{c.title}</p>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-text-muted">
                  {c.message_count} msg{c.message_count !== 1 ? "s" : ""}
                </span>
                {branches.length > 0 && <BranchIndicator branches={branches} />}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteConversation(c.id);
              }}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-muted hover:bg-error/20 hover:text-error md:invisible md:group-hover:visible"
            >
              <Trash2 size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function BranchIndicator({ branches }: { branches: string[] }) {
  const [open, setOpen] = useState(false);

  if (branches.length === 1) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] text-text-muted" title={branches[0]}>
        <GitBranch size={9} className="shrink-0" />
        1 branch
      </span>
    );
  }

  return (
    <span className="relative inline-flex items-center">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="inline-flex items-center gap-0.5 text-[10px] text-text-muted hover:text-accent transition-colors"
        title={branches.join(", ")}
      >
        <GitBranch size={9} className="shrink-0" />
        {branches.length} branches
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); setOpen(false); }} />
          <div className="absolute left-0 top-full z-50 mt-1 w-48 rounded-md border border-border-subtle bg-bg-surface py-1 shadow-lg">
            {branches.map((b) => (
              <div key={b} className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] text-text-secondary">
                <GitBranch size={10} className="shrink-0 text-text-muted" />
                <span className="truncate">{b}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </span>
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
        <Card key={m.id} size="sm" className="group ring-0 rounded-md border border-border-subtle bg-bg-surface">
          <CardContent className="p-2">
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
          <Card key={d.id} size="sm" className="group ring-0 rounded-md border border-border-subtle bg-bg-surface">
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
                <div className="flex gap-1">
                  <button
                    onClick={() => isPinned ? unpinDocument(d.id) : pinDocument(d.id)}
                    className={`text-text-muted hover:text-accent transition-colors ${isPinned ? "!visible text-accent" : "invisible group-hover:visible"}`}
                    title={isPinned ? "Unpin from context" : "Pin to context"}
                  >
                    {isPinned ? <PinOff size={10} /> : <Pin size={10} />}
                  </button>
                  <button
                    onClick={() => deleteDocument(d.id)}
                    className="invisible text-text-muted hover:text-error group-hover:visible"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

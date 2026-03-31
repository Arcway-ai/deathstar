import { useState } from "react";
import { X, Cpu, Brain } from "lucide-react";
import { useStore } from "../store";
import type { ProviderName } from "../types";

export default function SettingsPanel() {
  const toggleSettings = useStore((s) => s.toggleSettings);
  const [tab, setTab] = useState<"providers" | "memory">("providers");

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60"
        onClick={toggleSettings}
      />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-border-subtle bg-bg-primary animate-slide-right">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <h2 className="font-display text-sm font-bold text-text-primary">
            Settings
          </h2>
          <button
            onClick={toggleSettings}
            className="flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border-subtle">
          {[
            { id: "providers" as const, icon: Cpu, label: "Providers" },
            { id: "memory" as const, icon: Brain, label: "Memory" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors ${
                tab === t.id
                  ? "border-b-2 border-accent text-accent"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              <t.icon size={14} />
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {tab === "providers" && <ProvidersTab />}
          {tab === "memory" && <MemoryTab />}
        </div>
      </div>
    </>
  );
}

function ProvidersTab() {
  const providers = useStore((s) => s.providers);
  const selectedProvider = useStore((s) => s.selectedProvider);
  const setProvider = useStore((s) => s.setProvider);

  return (
    <div className="space-y-2">
      {Object.entries(providers).map(([name, status]) => (
        <button
          key={name}
          onClick={() => setProvider(name as ProviderName)}
          className={`flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${
            name === selectedProvider
              ? "border-accent/50 bg-accent-muted"
              : "border-border-subtle bg-bg-surface hover:border-border-default"
          }`}
        >
          <div
            className={`h-2 w-2 rounded-full ${
              status.configured ? "bg-success" : "bg-text-muted"
            }`}
          />
          <div>
            <p className="text-xs font-medium text-text-primary capitalize">
              {name}
            </p>
            <p className="text-[10px] text-text-muted font-mono">
              {status.default_model}
            </p>
          </div>
          {name === selectedProvider && (
            <span className="ml-auto text-[10px] text-accent">Active</span>
          )}
        </button>
      ))}
      {Object.keys(providers).length === 0 && (
        <p className="py-4 text-center text-xs text-text-muted">
          No providers configured
        </p>
      )}
    </div>
  );
}

function MemoryTab() {
  const memories = useStore((s) => s.memories);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const loadMemories = useStore((s) => s.loadMemories);
  const deleteMemory = useStore((s) => s.deleteMemory);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-text-secondary">
          {memories.length} memories{selectedRepo ? ` for ${selectedRepo}` : ""}
        </p>
        <button
          onClick={() => loadMemories(selectedRepo ?? undefined)}
          className="text-xs text-accent hover:text-accent-hover"
        >
          Refresh
        </button>
      </div>
      {memories.length === 0 ? (
        <div className="py-8 text-center">
          <Brain size={24} className="mx-auto mb-2 text-text-muted" />
          <p className="text-xs text-text-muted">
            No memories yet. Thumbs-up responses to build your memory bank.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {memories.map((m) => (
            <div
              key={m.id}
              className="rounded-lg border border-border-subtle bg-bg-surface p-3"
            >
              <p className="text-xs text-text-secondary line-clamp-4 whitespace-pre-wrap">
                {m.content}
              </p>
              <div className="mt-2 flex items-center justify-between">
                <div className="flex flex-wrap gap-1">
                  {m.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
                <button
                  onClick={() => deleteMemory(m.id)}
                  className="text-[10px] text-text-muted hover:text-error"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

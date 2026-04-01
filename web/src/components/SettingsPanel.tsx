import { useState } from "react";
import { Cpu, Brain } from "lucide-react";
import { useStore } from "../store";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ProviderName } from "../types";

export default function SettingsPanel() {
  const settingsOpen = useStore((s) => s.settingsOpen);
  const toggleSettings = useStore((s) => s.toggleSettings);
  const [tab, setTab] = useState<"providers" | "memory">("providers");

  return (
    <Sheet open={settingsOpen} onOpenChange={() => toggleSettings()}>
      <SheetContent side="right" className="w-full sm:max-w-md bg-bg-primary border-border-subtle flex flex-col gap-0 p-0">
        <SheetHeader className="px-4 py-3 border-b border-border-subtle">
          <SheetTitle className="font-display text-sm font-bold text-text-primary">
            Settings
          </SheetTitle>
        </SheetHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as "providers" | "memory")}
          className="flex flex-1 flex-col overflow-hidden"
        >
          <TabsList variant="line" className="w-full shrink-0 rounded-none border-b border-border-subtle bg-transparent p-0">
            <TabsTrigger
              value="providers"
              className="flex-1 gap-1.5 rounded-none py-2.5 text-xs text-text-muted data-active:text-accent data-active:after:bg-accent"
            >
              <Cpu size={14} />
              Providers
            </TabsTrigger>
            <TabsTrigger
              value="memory"
              className="flex-1 gap-1.5 rounded-none py-2.5 text-xs text-text-muted data-active:text-accent data-active:after:bg-accent"
            >
              <Brain size={14} />
              Memory
            </TabsTrigger>
          </TabsList>

          <TabsContent value="providers" className="flex-1 overflow-y-auto p-4">
            <ProvidersTab />
          </TabsContent>
          <TabsContent value="memory" className="flex-1 overflow-y-auto p-4">
            <MemoryTab />
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function ProvidersTab() {
  const providers = useStore((s) => s.providers);
  const selectedProvider = useStore((s) => s.selectedProvider);
  const setProvider = useStore((s) => s.setProvider);

  return (
    <div className="space-y-2">
      {Object.entries(providers).map(([name, status]) => (
        <Card
          key={name}
          size="sm"
          className={`ring-0 rounded-lg cursor-pointer transition-colors ${
            name === selectedProvider
              ? "border border-accent/50 bg-accent-muted"
              : "border border-border-subtle bg-bg-surface hover:border-border-default"
          }`}
          onClick={() => setProvider(name as ProviderName)}
        >
          <CardContent className="flex items-center gap-3 px-4 py-3">
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
              <Badge variant="secondary" className="ml-auto h-4 px-1.5 text-[10px] text-accent">
                Active
              </Badge>
            )}
          </CardContent>
        </Card>
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
            <Card key={m.id} size="sm" className="ring-0 rounded-lg border border-border-subtle bg-bg-surface">
              <CardContent className="p-3">
                <p className="text-xs text-text-secondary line-clamp-4 whitespace-pre-wrap">
                  {m.content}
                </p>
                <div className="mt-2 flex items-center justify-between">
                  <div className="flex flex-wrap gap-1">
                    {m.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="h-4 px-1.5 text-[10px] text-text-muted">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <button
                    onClick={() => deleteMemory(m.id)}
                    className="text-[10px] text-text-muted hover:text-error"
                  >
                    Remove
                  </button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { Zap, Star, ChevronDown, Sparkles } from "lucide-react";
import { useStore } from "../store";
import { modelsForProvider, SPEED_META, PRICE_META } from "../models";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import type { ModelInfo } from "../models";
import type { WorkflowKind } from "../types";

export default function ModelSelector() {
  const selectedProvider = useStore((s) => s.selectedProvider);
  const selectedModel = useStore((s) => s.selectedModel);
  const providers = useStore((s) => s.providers);
  const setModel = useStore((s) => s.setModel);
  const workflow = useStore((s) => s.workflow);
  const [open, setOpen] = useState(false);

  if (!selectedProvider) return null;

  const models = modelsForProvider(selectedProvider);
  const sortedModels = [...models].sort((a, b) => {
    const aForWorkflow = a.recommendedFor?.includes(workflow) ? 1 : 0;
    const bForWorkflow = b.recommendedFor?.includes(workflow) ? 1 : 0;
    if (aForWorkflow !== bForWorkflow) return bForWorkflow - aForWorkflow;
    const aRec = a.recommended ? 1 : 0;
    const bRec = b.recommended ? 1 : 0;
    return bRec - aRec;
  });
  const providerStatus = providers[selectedProvider];
  const activeModel = models.find((m) => m.id === selectedModel);
  const displayName = activeModel?.name ?? providerStatus?.default_model ?? "Default";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className="flex items-center gap-1.5 rounded-md bg-bg-surface px-2 py-1 text-xs hover:bg-bg-hover transition-colors"
        title={displayName}
      >
        <Zap size={12} className="text-text-muted" />
        <span className="hidden sm:inline font-mono text-text-secondary max-w-[120px] truncate">
          {displayName}
        </span>
        <ChevronDown size={10} className="text-text-muted" />
      </PopoverTrigger>

      <PopoverContent align="start" className="w-80 gap-0 p-0 border-border-subtle bg-bg-surface">
        <div className="border-b border-border-subtle px-3 py-2">
          <span className="text-xs font-medium text-text-secondary capitalize">
            {selectedProvider} Models
          </span>
        </div>

        <div className="max-h-72 overflow-y-auto p-1">
          {/* Default option */}
          <button
            onClick={() => { setModel(null); setOpen(false); }}
            className={`flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition-colors ${
              !selectedModel ? "bg-accent-muted" : "hover:bg-bg-hover"
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-text-primary">Default</span>
                <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] font-mono text-text-muted">
                  {providerStatus?.default_model}
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-text-muted">
                Use the server-configured default model
              </p>
            </div>
          </button>

          {sortedModels.map((model) => (
            <ModelRow
              key={model.id}
              model={model}
              selected={selectedModel === model.id}
              workflow={workflow}
              onSelect={() => { setModel(model.id); setOpen(false); }}
            />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ModelRow({
  model,
  selected,
  workflow,
  onSelect,
}: {
  model: ModelInfo;
  selected: boolean;
  workflow: WorkflowKind;
  onSelect: () => void;
}) {
  const speedMeta = SPEED_META[model.speed];
  const priceMeta = PRICE_META[model.price];
  const isRecommendedForWorkflow = model.recommendedFor?.includes(workflow);

  return (
    <button
      onClick={onSelect}
      className={`flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition-colors ${
        selected
          ? "bg-accent-muted"
          : isRecommendedForWorkflow
            ? "bg-accent/5 hover:bg-accent/10"
            : "hover:bg-bg-hover"
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-text-primary">
            {model.name}
          </span>
          {isRecommendedForWorkflow && (
            <Badge variant="secondary" className="h-4 gap-0.5 bg-accent/15 px-1.5 text-[9px] text-accent hover:bg-accent/15">
              <Sparkles size={8} />
              Best for {workflow}
            </Badge>
          )}
          {!isRecommendedForWorkflow && model.recommended && (
            <Star size={10} className="text-amber-400 fill-amber-400 shrink-0" />
          )}
        </div>
        <p className="mt-0.5 text-[10px] text-text-muted leading-snug">
          {model.description}
        </p>
        <div className="mt-1.5 flex items-center gap-1.5">
          <Badge variant="outline" className={`h-4 px-1.5 text-[10px] border-0 ${speedMeta.color}`}>
            {speedMeta.label}
          </Badge>
          <Badge variant="outline" className={`h-4 px-1.5 text-[10px] border-0 ${priceMeta.color}`}>
            {priceMeta.label}
          </Badge>
          <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
            {model.contextWindow} ctx
          </span>
          <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] font-mono text-text-muted" title={`$${model.pricing.inputPer1M}/M in · $${model.pricing.outputPer1M}/M out`}>
            ${model.pricing.inputPer1M}/${model.pricing.outputPer1M}
          </span>
        </div>
      </div>
    </button>
  );
}

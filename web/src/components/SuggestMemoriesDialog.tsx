import { Brain, Check, Loader2, X } from "lucide-react";
import { useStore } from "../store";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";

export default function SuggestMemoriesDialog() {
  const open = useStore((s) => s.suggestMemoriesOpen);
  const setOpen = useStore((s) => s.setSuggestMemoriesOpen);
  const suggestions = useStore((s) => s.suggestedMemories);
  const loading = useStore((s) => s.suggestingMemories);
  const approve = useStore((s) => s.approveMemorySuggestion);
  const dismiss = useStore((s) => s.dismissMemorySuggestion);

  const handleClose = () => {
    setOpen(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) handleClose();
      }}
    >
      <DialogContent className="sm:max-w-lg bg-bg-surface border-border-subtle">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-text-primary font-display">
            <Brain size={16} className="text-accent" />
            Suggested Memories
          </DialogTitle>
          <DialogDescription className="text-text-secondary text-xs">
            Knowledge extracted from this conversation. Approve items to save them to your memory bank for future context.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-80 overflow-y-auto space-y-2 py-1">
          {loading && (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <Loader2 size={20} className="animate-spin text-accent" />
              <p className="text-xs text-text-muted">Analyzing conversation...</p>
            </div>
          )}

          {!loading && suggestions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 gap-2 text-text-muted">
              <Brain size={20} />
              <p className="text-xs">No suggestions remaining</p>
            </div>
          )}

          {!loading &&
            suggestions.map((s, i) => (
              <div
                key={i}
                className="group rounded-lg border border-border-subtle bg-bg-deep/50 p-3 transition-colors hover:border-accent/20"
              >
                <p className="text-xs text-text-primary leading-relaxed mb-2">
                  {s.content}
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex gap-1 flex-wrap">
                    {s.tags.map((tag) => (
                      <Badge
                        key={tag}
                        variant="secondary"
                        className="text-[9px] px-1.5 py-0 bg-accent/10 text-accent border-accent/20"
                      >
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => approve(i)}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium text-success hover:bg-success/10 transition-colors"
                      title="Save to memory bank"
                    >
                      <Check size={10} />
                      Save
                    </button>
                    <button
                      onClick={() => dismiss(i)}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium text-text-muted hover:text-error hover:bg-error/10 transition-colors"
                      title="Dismiss"
                    >
                      <X size={10} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
        </div>

        {!loading && suggestions.length > 0 && (
          <DialogFooter className="border-border-subtle bg-bg-deep/30">
            <button
              onClick={async () => {
                // Approve all remaining
                for (let i = suggestions.length - 1; i >= 0; i--) {
                  await approve(0); // Always approve index 0 since array shifts
                }
              }}
              className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11px] font-medium bg-accent text-bg-deep hover:bg-accent-hover transition-colors"
            >
              <Check size={12} />
              Save All ({suggestions.length})
            </button>
            <button
              onClick={handleClose}
              className="rounded-md px-3 py-1.5 text-[11px] font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Done
            </button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

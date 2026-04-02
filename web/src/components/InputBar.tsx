import { useState, useRef, useEffect } from "react";
import { Send, AlertCircle, GitBranch, Pin, X } from "lucide-react";
import { useStore } from "../store";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function InputBar() {
  const text = useStore((s) => s.draftInput);
  const setText = useStore((s) => s.setDraftInput);
  const [branchModal, setBranchModal] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [creatingBranch, setCreatingBranch] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const branchInputRef = useRef<HTMLInputElement>(null);
  const sending = useStore((s) => s.sending);
  const compacting = useStore((s) => s.compacting);
  const sendError = useStore((s) => s.sendError);
  const sendMessage = useStore((s) => s.sendMessage);
  const sendAgentInput = useStore((s) => s.sendAgentInput);
  const agentStream = useStore((s) => s.agentStream);
  const repoContext = useStore((s) => s.repoContext);
  const workflow = useStore((s) => s.workflow);
  const contextFiles = useStore((s) => s.contextFiles);
  const unpinFile = useStore((s) => s.unpinFile);
  const pinFile = useStore((s) => s.pinFile);
  const createAndSwitchBranch = useStore((s) => s.createAndSwitchBranch);
  const [dragOver, setDragOver] = useState(false);

  const hasPendingPermission = agentStream.pendingPermission !== null;
  const isAgentWaitingForInput = sending && !agentStream.isStreaming && !hasPendingPermission;
  const isBusy = (sending && !isAgentWaitingForInput) || compacting;

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  // Focus branch name input when modal opens
  useEffect(() => {
    if (branchModal) branchInputRef.current?.focus();
  }, [branchModal]);

  const handleCreateBranchAndSend = async () => {
    const name = newBranchName.trim();
    if (!name) return;
    setCreatingBranch(true);
    setBranchError(null);
    try {
      await createAndSwitchBranch(name);
      setBranchModal(false);
      const trimmed = text.trim();
      if (trimmed) {
        sendMessage(trimmed);
        setText("");
      }
    } catch (e) {
      setBranchError(e instanceof Error ? e.message : "Failed to create branch");
    } finally {
      setCreatingBranch(false);
    }
  };

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;

    // Branch guard: block code changes on main/master
    if (repoContext?.branch === "main" || repoContext?.branch === "master") {
      if (workflow === "patch" || workflow === "pr") {
        setBranchModal(true);
        setNewBranchName("");
        setBranchError(null);
        return;
      }
    }

    if (isAgentWaitingForInput) {
      sendAgentInput(trimmed);
    } else {
      sendMessage(trimmed);
    }
    setText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const placeholder = isAgentWaitingForInput
    ? "Claude is waiting for your response..."
    : isBusy
      ? "Type a message to queue for when the agent finishes…"
      : "Ask about this codebase…";

  return (
    <div>
      {/* Branch guard modal */}
      <Dialog open={branchModal} onOpenChange={setBranchModal}>
        <DialogContent className="border-border-subtle bg-bg-surface sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-text-primary">
              <GitBranch size={18} className="text-warning" />
              Create a feature branch
            </DialogTitle>
            <DialogDescription className="text-text-secondary">
              You&apos;re on <span className="font-mono font-semibold text-warning">{repoContext?.branch}</span>.
              Code changes should be made on a feature branch to keep the default branch clean and enable pull request workflows.
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2 mt-2">
            <Input
              ref={branchInputRef}
              value={newBranchName}
              onChange={(e) => setNewBranchName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateBranchAndSend();
              }}
              placeholder="feature/my-change"
              className="flex-1 font-mono border-border-subtle bg-bg-primary text-text-primary placeholder:text-text-muted"
            />
            <Button
              onClick={handleCreateBranchAndSend}
              disabled={!newBranchName.trim() || creatingBranch}
            >
              {creatingBranch ? "Creating..." : "Create & send"}
            </Button>
          </div>
          {branchError && (
            <p className="text-xs text-error">{branchError}</p>
          )}
        </DialogContent>
      </Dialog>

      {sendError && (
        <Alert variant="destructive" className="mb-2 border-error/30 bg-error/10 py-1.5 text-xs text-error [&>svg]:text-error">
          <AlertCircle className="size-3" />
          <AlertDescription className="text-xs text-error">{sendError}</AlertDescription>
        </Alert>
      )}

      {/* Pinned context files */}
      {contextFiles.length > 0 && (
        <div className="mb-1.5 flex flex-wrap items-center gap-1">
          <Pin size={10} className="text-accent shrink-0" />
          {contextFiles.map((path) => {
            const fileName = path.split("/").pop() ?? path;
            return (
              <span
                key={path}
                className="inline-flex items-center gap-1 rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] font-mono text-accent"
                title={path}
              >
                {fileName}
                <button
                  onClick={() => unpinFile(path)}
                  className="text-accent/60 hover:text-accent transition-colors"
                >
                  <X size={8} />
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* Input + agent controls */}
      <div
        className={`flex items-end gap-2 rounded-xl border bg-bg-surface p-2 transition-colors ${
          dragOver
            ? "border-accent bg-accent/5"
            : "border-border-subtle focus-within:border-accent/50"
        }`}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes("text/plain")) {
            e.preventDefault();
            setDragOver(true);
          }
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const filePath = e.dataTransfer.getData("text/plain");
          if (filePath && !filePath.includes("\n")) {
            pinFile(filePath);
          }
        }}
      >
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={dragOver ? "Drop file to pin as context…" : placeholder}
          rows={1}
          className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-text-primary placeholder:text-text-muted outline-none"
        />
        <button
          onClick={handleSubmit}
          disabled={!text.trim()}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-bg-deep transition-opacity disabled:opacity-30 hover:bg-accent-hover"
        >
          <Send size={14} />
        </button>
      </div>

      <p className="mt-1 hidden text-center text-[10px] text-text-muted sm:block">
        Shift+Enter for new line · Enter to {isBusy ? "queue" : "send"}
      </p>
    </div>
  );
}

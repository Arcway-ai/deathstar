import { useState, useRef, useEffect } from "react";
import { Loader2, LogOut, Key } from "lucide-react";
import { useStore } from "../store";

export default function ClaudeAuth() {
  const claudeAuth = useStore((s) => s.claudeAuth);
  const claudeAuthSubmitting = useStore((s) => s.claudeAuthSubmitting);
  const submitClaudeToken = useStore((s) => s.submitClaudeToken);
  const claudeLogout = useStore((s) => s.claudeLogout);

  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const tokenInputRef = useRef<HTMLInputElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleMouseDown(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [open]);

  // Auto-focus token input when dropdown opens and not authenticated
  useEffect(() => {
    if (open && !claudeAuth.authenticated && tokenInputRef.current) {
      setTimeout(() => tokenInputRef.current?.focus(), 100);
    }
  }, [open, claudeAuth.authenticated]);

  const handleSubmitToken = async (e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!token.trim() || claudeAuthSubmitting) return;
    const success = await submitClaudeToken(token.trim());
    if (success) {
      setToken("");
      setOpen(false);
    }
  };

  const handleLogout = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    await claudeLogout();
    setOpen(false);
  };

  if (claudeAuth.loading) {
    return (
      <div className="flex h-8 w-8 items-center justify-center">
        <Loader2 size={14} className="animate-spin text-text-muted" />
      </div>
    );
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex h-8 items-center gap-1.5 rounded-md px-2 text-xs transition-colors hover:bg-bg-hover"
        title={claudeAuth.authenticated ? "Claude: Connected" : "Claude: Not connected"}
      >
        <span
          className={`h-2 w-2 rounded-full ${
            claudeAuth.authenticated ? "bg-success" : "bg-error animate-pulse"
          }`}
        />
        <span className="text-text-muted hidden sm:inline">Claude</span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full z-50 mt-1 w-80 rounded-lg border border-border-subtle bg-bg-surface shadow-xl"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="border-b border-border-subtle px-4 py-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  claudeAuth.authenticated ? "bg-success" : "bg-error"
                }`}
              />
              <span className="text-sm font-medium text-text-primary">
                {claudeAuth.authenticated ? "Connected" : "Not Connected"}
              </span>
            </div>
            {claudeAuth.message && (
              <p className="mt-1 text-[11px] text-text-muted truncate">{claudeAuth.message}</p>
            )}
          </div>

          <div className="p-3">
            {claudeAuth.authenticated ? (
              <button
                onClick={handleLogout}
                className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border-subtle px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover transition-colors"
              >
                <LogOut size={12} />
                Disconnect
              </button>
            ) : (
              <div className="space-y-2.5">
                <p className="text-[11px] text-text-secondary">
                  Run <code className="text-accent">npx @anthropic-ai/claude-code setup-token</code> locally, then paste the token:
                </p>
                <form onSubmit={handleSubmitToken} className="flex gap-1.5">
                  <div className="relative flex-1">
                    <Key size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                    <input
                      ref={tokenInputRef}
                      type="password"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder="Paste token..."
                      className="w-full rounded-md border border-border-subtle bg-bg-deep pl-7 pr-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted outline-none focus:border-accent/50 font-mono transition-colors"
                      disabled={claudeAuthSubmitting}
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={!token.trim() || claudeAuthSubmitting}
                    className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
                  >
                    {claudeAuthSubmitting ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      "Connect"
                    )}
                  </button>
                </form>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

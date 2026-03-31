import { Loader2, CircleAlert, Terminal, Key } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { useStore } from "../store";
import { DeathStarSpinner } from "./DeathStarLoader";
import Starfield from "./Starfield";

export default function AuthGate() {
  const claudeAuth = useStore((s) => s.claudeAuth);
  const claudeAuthSubmitting = useStore((s) => s.claudeAuthSubmitting);
  const submitClaudeToken = useStore((s) => s.submitClaudeToken);
  const [token, setToken] = useState("");
  const tokenInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!claudeAuth.loading && tokenInputRef.current) {
      setTimeout(() => tokenInputRef.current?.focus(), 100);
    }
  }, [claudeAuth.loading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim() || claudeAuthSubmitting) return;
    const success = await submitClaudeToken(token.trim());
    if (success) {
      setToken("");
    }
  };

  return (
    <div className="relative flex flex-1 items-center justify-center p-4 overflow-y-auto">
      <Starfield />
      <div className="relative z-10 w-full max-w-md animate-fade-in">
        <div className="mb-6 text-center">
          <DeathStarSpinner size={56} className="mx-auto mb-3" />
          <h1 className="font-display text-2xl font-bold text-text-primary mb-1">
            Connect Claude
          </h1>
          <p className="text-sm text-text-muted">
            Authenticate with your Claude Code subscription to get started
          </p>
        </div>

        <div className="rounded-xl border border-border-subtle bg-bg-surface/80 backdrop-blur-sm p-5">
          {claudeAuth.loading ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <Loader2 size={24} className="animate-spin text-text-muted" />
              <p className="text-xs text-text-muted">Checking authentication...</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-start gap-2.5 rounded-lg bg-accent/10 px-4 py-3">
                <Terminal size={16} className="mt-0.5 shrink-0 text-accent" />
                <div>
                  <p className="text-sm font-medium text-text-primary">Generate a token locally</p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    Run this command on your local machine (where you have a browser):
                  </p>
                  <code className="mt-1.5 block rounded-md bg-bg-deep px-3 py-2 text-xs font-mono text-accent select-all">
                    npx @anthropic-ai/claude-code setup-token
                  </code>
                </div>
              </div>

              <div className="flex items-start gap-2">
                <Key size={14} className="mt-0.5 shrink-0 text-text-muted" />
                <p className="text-sm text-text-secondary">
                  Paste the token here:
                </p>
              </div>

              <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                  ref={tokenInputRef}
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste token from setup-token..."
                  className="flex-1 rounded-lg border border-border-subtle bg-bg-deep px-3 py-2.5 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-accent/50 font-mono transition-colors"
                  disabled={claudeAuthSubmitting}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button
                  type="submit"
                  disabled={!token.trim() || claudeAuthSubmitting}
                  className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
                >
                  {claudeAuthSubmitting ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    "Connect"
                  )}
                </button>
              </form>

              {claudeAuth.message && !claudeAuth.authenticated && (
                <div className="flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2">
                  <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" />
                  <p className="text-[11px] text-text-muted">{claudeAuth.message}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

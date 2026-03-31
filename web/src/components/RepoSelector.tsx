import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  GitBranch,
  Folder,
  Globe,
  Search,
  Lock,
  Download,
  Check,
} from "lucide-react";
import { useStore } from "../store";
import { TIEFighterLoader, DeathStarSpinner } from "./DeathStarLoader";
import Starfield from "./Starfield";

export default function RepoSelector() {
  const [tab, setTab] = useState<"local" | "github">("local");
  const [search, setSearch] = useState("");

  return (
    <div className="relative flex flex-1 items-center justify-center p-4 overflow-y-auto">
      <Starfield />
      <div className="relative z-10 w-full max-w-xl animate-fade-in">
        {/* Header */}
        <div className="mb-6 text-center">
          <DeathStarSpinner size={56} className="mx-auto mb-3" />
          <h1 className="font-display text-3xl font-bold text-text-primary mb-1">
            DEATHSTAR
          </h1>
          <p className="text-sm text-text-muted">
            Select a workspace to begin
          </p>
        </div>

        {/* Search */}
        <div className="relative mb-4">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search repositories…"
            className="w-full rounded-lg border border-border-subtle bg-bg-surface py-2.5 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-accent/50 transition-colors"
          />
        </div>

        {/* Tabs */}
        <div className="mb-4 flex rounded-lg bg-bg-surface p-0.5">
          <button
            onClick={() => setTab("local")}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-xs font-medium transition-colors ${
              tab === "local"
                ? "bg-bg-elevated text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            <Folder size={14} />
            Local Repos
          </button>
          <button
            onClick={() => setTab("github")}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-xs font-medium transition-colors ${
              tab === "github"
                ? "bg-bg-elevated text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            <Globe size={14} />
            GitHub
          </button>
        </div>

        {/* Content */}
        {tab === "local" ? (
          <LocalRepoList search={search} />
        ) : (
          <GitHubRepoList search={search} />
        )}
      </div>
    </div>
  );
}

function LocalRepoList({ search }: { search: string }) {
  const navigate = useNavigate();
  const repos = useStore((s) => s.repos);
  const repoLoading = useStore((s) => s.repoLoading);
  const loadRepos = useStore((s) => s.loadRepos);

  const filtered = repos.filter((r) =>
    r.name.toLowerCase().includes(search.toLowerCase()),
  );

  if (repoLoading) {
    return <TIEFighterLoader text="Scanning" />;
  }

  if (repos.length === 0) {
    return (
      <div className="py-12 text-center">
        <Folder size={32} className="mx-auto mb-3 text-text-muted" />
        <p className="text-sm text-text-muted mb-3">
          No repos found on the remote instance.
        </p>
        <button
          onClick={loadRepos}
          className="rounded-md border border-border-subtle px-4 py-2 text-xs text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {filtered.map((repo) => (
        <button
          key={repo.name}
          onClick={() => navigate(`/${encodeURIComponent(repo.name)}`)}
          className="flex w-full items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface px-4 py-3 text-left transition-all hover:border-accent/30 hover:bg-bg-elevated group"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent group-hover:bg-accent/20 transition-colors">
            <Folder size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-text-primary truncate">
              {repo.name}
            </p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="flex items-center gap-1 text-[11px] text-text-muted font-mono">
                <GitBranch size={10} />
                {repo.branch}
              </span>
              {repo.dirty && (
                <span className="text-[10px] text-warning">modified</span>
              )}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

function GitHubRepoList({ search }: { search: string }) {
  const githubRepos = useStore((s) => s.githubRepos);
  const githubLoading = useStore((s) => s.githubLoading);
  const loadGitHubRepos = useStore((s) => s.loadGitHubRepos);
  const cloneRepo = useStore((s) => s.cloneRepo);
  const repos = useStore((s) => s.repos);
  const [cloning, setCloning] = useState<string | null>(null);
  const [cloneError, setCloneError] = useState<string | null>(null);

  useEffect(() => {
    if (githubRepos.length === 0) {
      loadGitHubRepos();
    }
  }, [githubRepos.length, loadGitHubRepos]);

  const filtered = githubRepos.filter(
    (r) =>
      r.full_name.toLowerCase().includes(search.toLowerCase()) ||
      (r.description ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const localRepoNames = new Set(repos.map((r) => r.name));

  const handleClone = async (fullName: string) => {
    setCloning(fullName);
    setCloneError(null);
    try {
      await cloneRepo(fullName);
    } catch (e) {
      setCloneError(
        `Failed to clone ${fullName}: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    } finally {
      setCloning(null);
    }
  };

  if (githubLoading) {
    return <TIEFighterLoader text="Fetching" />;
  }

  if (githubRepos.length === 0) {
    return (
      <div className="py-12 text-center">
        <Globe size={32} className="mx-auto mb-3 text-text-muted" />
        <p className="text-sm text-text-muted mb-3">
          Unable to fetch GitHub repos.
          <br />
          Ensure GITHUB_TOKEN is set on the instance.
        </p>
        <button
          onClick={loadGitHubRepos}
          className="rounded-md border border-border-subtle px-4 py-2 text-xs text-text-secondary hover:border-border-default hover:text-text-primary transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1 max-h-[50vh] overflow-y-auto">
      {cloneError && (
        <div className="rounded-lg border border-error/30 bg-error/10 px-3 py-2 text-xs text-error mb-2">
          {cloneError}
        </div>
      )}
      {filtered.map((repo) => {
        const alreadyCloned = localRepoNames.has(repo.name);
        const isCloning = cloning === repo.full_name;

        return (
          <div
            key={repo.full_name}
            className="flex items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface px-4 py-3 transition-all hover:border-border-default"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <p className="text-sm font-medium text-text-primary truncate">
                  {repo.full_name}
                </p>
                {repo.private && <Lock size={10} className="shrink-0 text-text-muted" />}
              </div>
              {repo.description && (
                <p className="text-[11px] text-text-muted mt-0.5 truncate">
                  {repo.description}
                </p>
              )}
              <div className="flex items-center gap-2 mt-0.5">
                {repo.language && (
                  <span className="text-[10px] text-text-muted">
                    {repo.language}
                  </span>
                )}
              </div>
            </div>

            {alreadyCloned ? (
              <span className="flex items-center gap-1 text-xs text-success">
                <Check size={12} />
                Cloned
              </span>
            ) : (
              <button
                onClick={() => handleClone(repo.full_name)}
                disabled={isCloning}
                className="flex items-center gap-1 rounded-md border border-border-subtle px-2.5 py-1.5 text-xs text-text-secondary hover:border-accent hover:text-accent transition-colors disabled:opacity-50"
              >
                {isCloning ? (
                  <DeathStarSpinner size={14} />
                ) : (
                  <Download size={12} />
                )}
                Clone
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

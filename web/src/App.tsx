import { useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "./store";
import { initSession } from "./api";
import { applyTheme } from "./themes";
import AuthGate from "./components/AuthGate";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import RepoPanel from "./components/RepoPanel";
import ChatView from "./components/ChatView";
import RepoSelector from "./components/RepoSelector";
import FileViewer from "./components/FileViewer";
import TerminalPanel from "./components/Terminal";
import Superlaser from "./components/Superlaser";
import { ToastContainer } from "./components/Toast";

export default function App() {
  const { repo: urlRepo, conversationId: urlConversationId } = useParams();
  const navigate = useNavigate();

  const selectedRepo = useStore((s) => s.selectedRepo);
  const conversationId = useStore((s) => s.conversationId);
  const fileContent = useStore((s) => s.fileContent);
  const terminalOpen = useStore((s) => s.terminalOpen);
  const claudeAuth = useStore((s) => s.claudeAuth);
  const loadRepos = useStore((s) => s.loadRepos);
  const loadProviders = useStore((s) => s.loadProviders);
  const checkClaudeAuth = useStore((s) => s.checkClaudeAuth);

  const isAuthed = claudeAuth.authenticated;
  const theme = useStore((s) => s.theme);

  // Track whether we've done the initial sync to avoid loops
  const initialSync = useRef(false);

  // Apply persisted theme on boot and when it changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Boot: ensure session cookie, then fetch repos, providers, auth status
  useEffect(() => {
    initSession().then(() => {
      loadRepos();
      loadProviders();
      checkClaudeAuth();
    });
  }, [loadRepos, loadProviders, checkClaudeAuth]);

  // URL → Store: sync URL params into the store on mount and URL changes
  useEffect(() => {
    const { selectedRepo: currentRepo, conversationId: currentConv, selectRepo, selectConversation, newConversation, loadBranches } =
      useStore.getState();

    if (urlRepo) {
      // URL has a repo — make sure the store matches
      if (currentRepo !== urlRepo) {
        selectRepo(urlRepo);
        loadBranches();
      }
      // URL has a conversation — load it
      if (urlConversationId && currentConv !== urlConversationId) {
        selectConversation(urlConversationId);
      } else if (!urlConversationId && currentConv) {
        // URL says "new conversation" for this repo
        newConversation();
      }
    } else {
      // URL is "/" — clear repo selection
      if (currentRepo) {
        useStore.setState({ selectedRepo: null, conversationId: null, activeConversation: null });
      }
    }
    initialSync.current = true;

    // Load server-side message queue
    if (urlRepo) {
      setTimeout(() => useStore.getState().loadQueue(), 500);
    }
  }, [urlRepo, urlConversationId]);

  // Store → URL: when the store changes, update the URL to match
  useEffect(() => {
    if (!initialSync.current) return;

    // Build the expected path from store state
    let expectedPath = "/";
    if (selectedRepo) {
      expectedPath = `/${encodeURIComponent(selectedRepo)}`;
      if (conversationId) {
        expectedPath += `/c/${encodeURIComponent(conversationId)}`;
      }
    }

    // Decode current path for comparison
    const currentPath = decodeURIComponent(window.location.pathname);
    const expectedDecoded = decodeURIComponent(expectedPath);

    if (currentPath !== expectedDecoded) {
      navigate(expectedPath, { replace: true });
    }
  }, [selectedRepo, conversationId, navigate]);

  // Cmd+S / Ctrl+S → quick save
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        const { selectedRepo, quickSave } = useStore.getState();
        if (selectedRepo) quickSave();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex h-full flex-col bg-bg-deep">
      <TopBar />
      <div className="relative flex flex-1 overflow-hidden">
        {isAuthed && <Sidebar />}
        {/* Mobile sidebar backdrop */}
        {isAuthed && <SidebarBackdrop />}
        <div className="flex flex-1 flex-col overflow-hidden">
          <main className="flex flex-1 flex-col overflow-hidden">
            {!isAuthed ? (
              <AuthGate />
            ) : !selectedRepo ? (
              <RepoSelector />
            ) : fileContent ? (
              <FileViewer />
            ) : (
              <ChatView />
            )}
          </main>
          {terminalOpen && selectedRepo && isAuthed && <TerminalPanel />}
        </div>
        {isAuthed && <RepoPanel />}
      </div>
      <Superlaser />
      <ToastContainer />
    </div>
  );
}

function SidebarBackdrop() {
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  if (!sidebarOpen) return null;
  return (
    <div
      className="fixed inset-0 z-30 bg-black/50 md:hidden"
      onClick={toggleSidebar}
    />
  );
}

import { useEffect } from "react";
import { useStore } from "./store";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import RepoSelector from "./components/RepoSelector";
import SettingsPanel from "./components/SettingsPanel";
import FileViewer from "./components/FileViewer";

export default function App() {
  const selectedRepo = useStore((s) => s.selectedRepo);
  const fileContent = useStore((s) => s.fileContent);
  const settingsOpen = useStore((s) => s.settingsOpen);
  const loadRepos = useStore((s) => s.loadRepos);
  const loadProviders = useStore((s) => s.loadProviders);

  useEffect(() => {
    loadRepos();
    loadProviders();
  }, [loadRepos, loadProviders]);

  return (
    <div className="flex h-full flex-col bg-bg-deep">
      <TopBar />
      <div className="relative flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex flex-1 flex-col overflow-hidden">
          {!selectedRepo ? (
            <RepoSelector />
          ) : fileContent ? (
            <FileViewer />
          ) : (
            <ChatView />
          )}
        </main>
      </div>
      {settingsOpen && <SettingsPanel />}
    </div>
  );
}

import { ArrowLeft } from "lucide-react";
import { useStore } from "../store";

export default function FileViewer() {
  const fileContent = useStore((s) => s.fileContent);
  const closeFile = useStore((s) => s.closeFile);

  if (!fileContent) return null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border-subtle bg-bg-primary px-4 py-2">
        <button
          onClick={closeFile}
          className="flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <span className="font-mono text-xs text-text-secondary truncate">
          {fileContent.path}
        </span>
      </div>

      {/* Code */}
      <div className="flex-1 overflow-auto bg-bg-deep p-4">
        <pre className="font-mono text-xs leading-relaxed text-text-primary">
          <code>
            {fileContent.content.split("\n").map((line, i) => (
              <div key={i} className="flex hover:bg-bg-surface/50">
                <span className="w-12 shrink-0 select-none pr-4 text-right text-text-muted">
                  {i + 1}
                </span>
                <span className="flex-1 whitespace-pre-wrap break-all">
                  {line}
                </span>
              </div>
            ))}
          </code>
        </pre>
      </div>
    </div>
  );
}

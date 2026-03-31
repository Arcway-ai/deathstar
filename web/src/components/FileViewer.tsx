import { useEffect, useRef, useState } from "react";
import { X, Copy, Check, FileCode, ChevronRight } from "lucide-react";
import hljs from "highlight.js/lib/core";
import { useStore } from "../store";
import { detectLanguage } from "../fileTree";

// Register commonly used languages
import typescript from "highlight.js/lib/languages/typescript";
import javascript from "highlight.js/lib/languages/javascript";
import python from "highlight.js/lib/languages/python";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import yaml from "highlight.js/lib/languages/yaml";
import css from "highlight.js/lib/languages/css";
import xml from "highlight.js/lib/languages/xml";
import sql from "highlight.js/lib/languages/sql";
import go from "highlight.js/lib/languages/go";
import rust from "highlight.js/lib/languages/rust";
import markdown from "highlight.js/lib/languages/markdown";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import ini from "highlight.js/lib/languages/ini";
import scss from "highlight.js/lib/languages/scss";

hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("css", css);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("go", go);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("dockerfile", dockerfile);
hljs.registerLanguage("ini", ini);
hljs.registerLanguage("scss", scss);

export default function FileViewer() {
  const fileContent = useStore((s) => s.fileContent);
  const closeFile = useStore((s) => s.closeFile);
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLDivElement>(null);

  const path = fileContent?.path ?? "";
  const content = fileContent?.content ?? "";
  const lang = detectLanguage(path);
  const lines = content.split("\n");
  const lineCount = lines.length;

  // Highlight code
  const highlighted = useHighlight(content, lang);

  if (!fileContent) return null;

  const pathParts = path.split("/");
  const fileName = pathParts[pathParts.length - 1];

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden animate-fade-in">
      {/* Header bar */}
      <div className="flex items-center gap-2 border-b border-border-subtle bg-bg-primary px-3 py-1.5">
        {/* Breadcrumb path */}
        <FileCode size={14} className="shrink-0 text-text-muted" />
        <div className="flex items-center gap-0.5 overflow-x-auto text-xs">
          {pathParts.map((part, i) => (
            <span key={i} className="flex items-center gap-0.5 shrink-0">
              {i > 0 && (
                <ChevronRight
                  size={10}
                  className="text-text-muted"
                />
              )}
              <span
                className={
                  i === pathParts.length - 1
                    ? "font-medium text-text-primary"
                    : "text-text-muted"
                }
              >
                {part}
              </span>
            </span>
          ))}
        </div>

        <div className="flex-1" />

        {/* Language badge */}
        {lang && (
          <span className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
            {lang}
          </span>
        )}

        {/* Line count */}
        <span className="text-[10px] text-text-muted">
          {lineCount} {lineCount === 1 ? "line" : "lines"}
        </span>

        {/* Copy */}
        <button
          onClick={handleCopy}
          className="flex h-6 w-6 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
          title="Copy file contents"
        >
          {copied ? (
            <Check size={12} className="text-success" />
          ) : (
            <Copy size={12} />
          )}
        </button>

        {/* Close */}
        <button
          onClick={closeFile}
          className="flex h-6 w-6 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
          title="Close file"
        >
          <X size={14} />
        </button>
      </div>

      {/* Code area */}
      <div ref={codeRef} className="flex-1 overflow-auto bg-bg-deep">
        <div className="min-w-fit">
          <table className="w-full border-collapse">
            <tbody>
              {highlighted.map((lineHtml, i) => (
                <tr
                  key={i}
                  className="group hover:bg-bg-surface/40 transition-colors duration-75"
                >
                  {/* Line number gutter */}
                  <td className="sticky left-0 w-[1px] select-none whitespace-nowrap bg-bg-deep pr-4 pl-3 text-right align-top font-mono text-[11px] leading-[1.65] text-text-muted/50 group-hover:text-text-muted">
                    {i + 1}
                  </td>
                  {/* Code line */}
                  <td
                    className="whitespace-pre px-4 align-top font-mono text-[12px] leading-[1.65] text-text-primary"
                    dangerouslySetInnerHTML={{ __html: lineHtml }}
                  />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Footer status */}
      <div className="flex items-center gap-3 border-t border-border-subtle bg-bg-primary px-3 py-1">
        <span className="font-mono text-[10px] text-text-muted">
          {fileName}
        </span>
        <div className="flex-1" />
        <span className="text-[10px] text-text-muted">
          UTF-8
        </span>
        {lang && (
          <span className="text-[10px] text-text-muted capitalize">
            {lang}
          </span>
        )}
      </div>
    </div>
  );
}

/** Highlights code and returns an array of HTML strings, one per line */
function useHighlight(code: string, lang: string | undefined): string[] {
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    if (!code) {
      setLines([]);
      return;
    }

    let html: string;
    try {
      if (lang && hljs.getLanguage(lang)) {
        html = hljs.highlight(code, { language: lang }).value;
      } else {
        html = hljs.highlightAuto(code).value;
      }
    } catch {
      // Fallback: escape HTML
      html = code
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    // Sanitize + split highlighted HTML by newlines, preserving open spans across lines
    setLines(splitHighlightedLines(sanitizeHljsHtml(html)));
  }, [code, lang]);

  return lines;
}

/** Strip any HTML tags that aren't hljs span tags (defense-in-depth). */
function sanitizeHljsHtml(html: string): string {
  // Allow only <span class="hljs-..."> and </span> — strip everything else
  return html.replace(/<(?!\/?span[\s>])[^>]*>/g, (match) => {
    return match.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  });
}

/**
 * Splits highlighted HTML into individual lines while keeping
 * span tags balanced (so a multi-line token stays colored on each line).
 */
function splitHighlightedLines(html: string): string[] {
  const rawLines = html.split("\n");
  const result: string[] = [];
  let openSpans: string[] = [];

  for (const rawLine of rawLines) {
    // Prepend any open spans from previous line
    let line = openSpans.join("") + rawLine;

    // Track open/close spans
    const opens = rawLine.match(/<span[^>]*>/g) ?? [];
    const closes = rawLine.match(/<\/span>/g) ?? [];

    // Update stack
    for (const open of opens) openSpans.push(open);
    for (let i = 0; i < closes.length; i++) openSpans.pop();

    // Close all open spans at end of this line
    line += "</span>".repeat(openSpans.length);

    result.push(line);
  }

  return result;
}

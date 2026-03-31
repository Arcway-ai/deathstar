import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { X, TerminalSquare, Maximize2, Minimize2, RotateCw } from "lucide-react";
import { useStore } from "../store";

type ConnectionState = "connecting" | "connected" | "disconnected";

const MAX_RETRIES = 5;
const BASE_DELAY = 1000; // 1s

export default function TerminalPanel() {
  const selectedRepo = useStore((s) => s.selectedRepo);
  const termRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);
  const [connState, setConnState] = useState<ConnectionState>("disconnected");
  const [maximized, setMaximized] = useState(false);
  const closeTerminal = useStore((s) => s.closeTerminal);

  const buildWsUrl = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const repoParam = selectedRepo
      ? `?repo=${encodeURIComponent(selectedRepo)}`
      : "";
    return `${protocol}//${window.location.host}/web/api/terminal${repoParam}`;
  }, [selectedRepo]);

  const connect = useCallback(() => {
    const term = xtermRef.current;
    const fitAddon = fitAddonRef.current;
    if (!term || !fitAddon) return;

    // Close existing connection if any
    if (wsRef.current) {
      intentionalCloseRef.current = true;
      wsRef.current.close();
      wsRef.current = null;
    }

    intentionalCloseRef.current = false;
    setConnState("connecting");

    const attempt = retriesRef.current;
    if (attempt > 0) {
      term.write(
        `\r\n\x1b[33m[reconnecting... attempt ${attempt}/${MAX_RETRIES}]\x1b[0m\r\n`
      );
    }

    const ws = new WebSocket(buildWsUrl());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setConnState("connected");
      if (attempt > 0) {
        term.write("\x1b[32m[reconnected]\x1b[0m\r\n");
      }
      // Send initial size
      const dims = fitAddon.proposeDimensions();
      if (dims) {
        ws.send(
          JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols })
        );
      }
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data));
      } else {
        term.write(event.data as string);
      }
    };

    ws.onclose = () => {
      if (intentionalCloseRef.current) return;
      setConnState("disconnected");

      if (retriesRef.current < MAX_RETRIES) {
        const delay = BASE_DELAY * Math.pow(2, retriesRef.current);
        retriesRef.current += 1;
        term.write(
          `\r\n\x1b[90m[disconnected — retrying in ${(delay / 1000).toFixed(0)}s]\x1b[0m\r\n`
        );
        retryTimerRef.current = setTimeout(connect, delay);
      } else {
        term.write(
          `\r\n\x1b[31m[disconnected — max retries reached. Click reconnect to try again.]\x1b[0m\r\n`
        );
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror, so let that handle retry
    };

    // Terminal input → WebSocket
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });
  }, [buildWsUrl]);

  const manualReconnect = useCallback(() => {
    // Reset retry counter and connect
    retriesRef.current = 0;
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    connect();
  }, [connect]);

  useEffect(() => {
    if (!termRef.current) return;

    const term = new XTerm({
      cursorBlink: true,
      cursorStyle: "bar",
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      lineHeight: 1.3,
      theme: {
        background: "#06080c",
        foreground: "#e2e8f0",
        cursor: "#4a9eff",
        cursorAccent: "#06080c",
        selectionBackground: "#4a9eff40",
        black: "#0c1018",
        red: "#f87171",
        green: "#34d399",
        yellow: "#fbbf24",
        blue: "#4a9eff",
        magenta: "#c084fc",
        cyan: "#22d3ee",
        white: "#e2e8f0",
        brightBlack: "#64748b",
        brightRed: "#fca5a5",
        brightGreen: "#6ee7b7",
        brightYellow: "#fde68a",
        brightBlue: "#93c5fd",
        brightMagenta: "#d8b4fe",
        brightCyan: "#67e8f9",
        brightWhite: "#f8fafc",
      },
      scrollback: 5000,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);

    term.open(termRef.current);
    fitAddon.fit();

    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    // Handle resize
    const handleResize = () => {
      fitAddon.fit();
      const dims = fitAddon.proposeDimensions();
      if (dims && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols })
        );
      }
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(termRef.current);

    return () => {
      resizeObserver.disconnect();
      intentionalCloseRef.current = true;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
      }
      wsRef.current?.close();
      term.dispose();
    };
  }, []);

  // Connect (or reconnect) when selectedRepo changes or on mount
  useEffect(() => {
    if (xtermRef.current && fitAddonRef.current) {
      retriesRef.current = 0;
      connect();
    }
  }, [selectedRepo, connect]);

  // Refit on maximize/minimize
  useEffect(() => {
    setTimeout(() => {
      fitAddonRef.current?.fit();
      const dims = fitAddonRef.current?.proposeDimensions();
      if (dims && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols })
        );
      }
    }, 50);
  }, [maximized]);

  const statusColor =
    connState === "connected"
      ? "bg-success"
      : connState === "connecting"
        ? "bg-warning animate-pulse"
        : "bg-error";
  const statusText =
    connState === "connected"
      ? "connected"
      : connState === "connecting"
        ? "connecting..."
        : "disconnected";

  return (
    <div
      className={`flex flex-col border-t border-border-subtle bg-bg-deep ${
        maximized ? "fixed inset-0 z-50" : "h-64 sm:h-72 md:h-80"
      }`}
    >
      {/* Terminal header */}
      <div className="flex items-center gap-2 border-b border-border-subtle bg-bg-primary px-3 py-1">
        <TerminalSquare size={12} className="text-text-muted" />
        <span className="text-[11px] font-medium text-text-secondary">
          Terminal
        </span>
        <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
        <span className="text-[10px] text-text-muted">{statusText}</span>

        {/* Reconnect button — visible when disconnected */}
        {connState === "disconnected" && (
          <button
            onClick={manualReconnect}
            className="ml-1 flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-accent hover:bg-bg-hover transition-colors"
            title="Reconnect terminal"
          >
            <RotateCw size={10} />
            Connect
          </button>
        )}

        <div className="flex-1" />

        <button
          onClick={() => setMaximized(!maximized)}
          className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
          title={maximized ? "Minimize" : "Maximize"}
        >
          {maximized ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
        </button>

        <button
          onClick={closeTerminal}
          className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-bg-hover hover:text-text-secondary transition-colors"
          title="Close terminal"
        >
          <X size={12} />
        </button>
      </div>

      {/* Terminal content */}
      <div ref={termRef} className="flex-1 overflow-hidden px-1 py-1" />
    </div>
  );
}

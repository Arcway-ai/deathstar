/**
 * WebSocket client for interactive Claude Code agent sessions.
 *
 * Manages the bidirectional connection to `/web/api/agent`, handles
 * reconnection, and provides typed callbacks for all message types.
 */

export type ConnectionState = "disconnected" | "connecting" | "connected";

export interface AgentStartConfig {
  repo: string;
  message: string;
  workflow: string;
  conversation_id?: string;
  model?: string;
  system?: string;
  auto_accept?: boolean;
}

export interface AgentStatusEvent {
  status: string;
  message: string;
  retry_delay_s?: number;
  attempt?: number;
  max_retries?: number;
}

export interface RepoEventData {
  event_type: string;
  repo: string;
  source: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface AgentCallbacks {
  onTextDelta: (text: string) => void;
  onThinking: (text: string) => void;
  onThinkingDelta: (text: string) => void;
  onToolUse: (id: string, tool: string, input: Record<string, unknown>) => void;
  onToolResult: (toolUseId: string, content: string, isError: boolean) => void;
  onPermissionRequest: (tool: string, input: Record<string, unknown>) => void;
  onResult: (data: AgentResult) => void;
  onError: (code: string, message: string) => void;
  onStarted: (conversationId: string) => void;
  onStateChange: (state: ConnectionState) => void;
  onCompactDone?: (summary: string) => void;
  onStatus?: (event: AgentStatusEvent) => void;
  onRepoEvent?: (event: RepoEventData) => void;
}

export interface AgentResult {
  conversation_id: string;
  message_id: string;
  session_id: string;
  model: string;
  duration_ms: number;
  num_turns: number;
  usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  cost_usd: number | null;
  content: string;
  status: "succeeded" | "failed";
}

export class AgentSocket {
  private ws: WebSocket | null = null;
  private callbacks: AgentCallbacks;
  private _state: ConnectionState = "disconnected";

  constructor(callbacks: AgentCallbacks) {
    this.callbacks = callbacks;
  }

  get state(): ConnectionState {
    return this._state;
  }

  /** Open a WebSocket connection to the agent endpoint. */
  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;

    this.setState("connecting");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/web/api/agent`;

    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      this.setState("connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      this.setState("disconnected");
      this.ws = null;
    };

    ws.onerror = () => {
      // onclose fires after onerror
    };
  }

  /** Send a start message to begin an agent interaction. */
  start(config: AgentStartConfig): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.connect();
      // Wait for connection then send
      const originalOnOpen = this.ws?.onopen;
      if (this.ws) {
        this.ws.onopen = (ev) => {
          if (typeof originalOnOpen === "function") originalOnOpen.call(this.ws!, ev);
          this.sendJson({ type: "start", ...config });
        };
      }
      return;
    }
    this.sendJson({ type: "start", ...config });
  }

  /** Send follow-up input to the running agent (like typing in a terminal). */
  sendInput(text: string): void {
    this.sendJson({ type: "input", text });
  }

  /** Respond to a permission request. */
  respondToPermission(allow: boolean): void {
    this.sendJson({ type: "permission_response", allow });
  }

  /** Interrupt the running agent. */
  interrupt(): void {
    this.sendJson({ type: "interrupt" });
  }

  /** Send a compact command to compress conversation context. */
  compact(): void {
    this.sendJson({ type: "compact" });
  }

  /** Subscribe to real-time repo events for a given repo. */
  subscribeEvents(repo: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.connect();
      const originalOnOpen = this.ws?.onopen;
      if (this.ws) {
        this.ws.onopen = (ev) => {
          if (typeof originalOnOpen === "function") originalOnOpen.call(this.ws!, ev);
          this.sendJson({ type: "subscribe_events", repo });
        };
      }
      return;
    }
    this.sendJson({ type: "subscribe_events", repo });
  }

  /** Disconnect the WebSocket. */
  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setState("disconnected");
  }

  private sendJson(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private setState(state: ConnectionState): void {
    this._state = state;
    this.callbacks.onStateChange(state);
  }

  private handleMessage(msg: Record<string, unknown>): void {
    const type = msg.type as string;

    switch (type) {
      case "text_delta":
        this.callbacks.onTextDelta(msg.text as string);
        break;
      case "thinking":
        this.callbacks.onThinking(msg.text as string);
        break;
      case "thinking_delta":
        this.callbacks.onThinkingDelta(msg.text as string);
        break;
      case "tool_use":
        this.callbacks.onToolUse(
          msg.id as string,
          msg.tool as string,
          msg.input as Record<string, unknown>,
        );
        break;
      case "tool_result":
        this.callbacks.onToolResult(
          msg.tool_use_id as string,
          msg.content as string,
          msg.is_error as boolean,
        );
        break;
      case "permission_request":
        this.callbacks.onPermissionRequest(
          msg.tool as string,
          msg.input as Record<string, unknown>,
        );
        break;
      case "started":
        this.callbacks.onStarted(msg.conversation_id as string);
        break;
      case "result":
        this.callbacks.onResult(msg as unknown as AgentResult);
        break;
      case "status":
        this.callbacks.onStatus?.(msg as unknown as AgentStatusEvent);
        break;
      case "compact_done":
        this.callbacks.onCompactDone?.(
          (msg.summary as string) ?? "Context compacted",
        );
        break;
      case "repo_event":
        this.callbacks.onRepoEvent?.(msg as unknown as RepoEventData);
        break;
      case "error":
        this.callbacks.onError(
          (msg.code as string) ?? "UNKNOWN",
          (msg.message as string) ?? "Unknown error",
        );
        break;
    }
  }
}

/**
 * WebSocket client for interactive Claude Code agent sessions.
 *
 * Manages the bidirectional connection to `/web/api/agent`, handles
 * automatic reconnection with exponential backoff, and provides typed
 * callbacks for all message types.
 *
 * Reconnect behaviour
 * -------------------
 * Once `connect()` is called, the socket will automatically reconnect
 * after any unexpected close (network drop, server restart, etc.) using
 * exponential backoff: 1 s → 2 s → 4 s … capped at 30 s.
 *
 * Call `disconnect()` to stop reconnecting and close the socket cleanly.
 *
 * Pending-message queue
 * ---------------------
 * `start()` and `subscribeEvents()` may be called before (or during) a
 * connection attempt.  They push their payload onto `_sendQueue`; the queue
 * is drained in `onopen` so no message is ever lost to a race between the
 * caller and the TCP handshake.  Only one queued "start" and one queued
 * "subscribe_events" message are kept at a time — a newer call silently
 * replaces the earlier one (the latest intent wins).
 */

export type ConnectionState = "disconnected" | "connecting" | "connected";

export interface AgentStartConfig {
  repo: string;
  branch?: string;
  message: string;
  workflow: string;
  conversation_id?: string;
  model?: string;
  system?: string;
  auto_accept?: boolean;
  context_files?: string[];
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

export interface AgentSnapshotData {
  status: string;
  text: string;
  blocks: Array<Record<string, unknown>>;
  conversation_id: string;
  repo: string;
  branch: string | null;
  workflow: string;
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
  onSnapshot?: (data: AgentSnapshotData) => void;
  onPRCreated?: (data: { pr_url: string; pr_number: number; pr_title: string; branch: string; base_branch: string; draft: boolean; user: string }) => void;
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

  /** Whether to reconnect automatically after an unexpected close. */
  private _shouldReconnect = false;
  /** Current reconnection attempt count — reset to 0 on successful open. */
  private _reconnectAttempt = 0;
  /** Pending setTimeout handle for the next reconnect attempt. */
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * Messages to send as soon as the connection opens.
   * At most one "start" and one "subscribe_events" entry are kept.
   */
  private _sendQueue: Array<Record<string, unknown>> = [];

  constructor(callbacks: AgentCallbacks) {
    this.callbacks = callbacks;
  }

  get state(): ConnectionState {
    return this._state;
  }

  /** Open the WebSocket and enable auto-reconnect on unexpected closes. */
  connect(): void {
    this._shouldReconnect = true;
    this._openConnection();
  }

  /** Send a start message to begin an agent interaction. */
  start(config: AgentStartConfig): void {
    const msg = { type: "start", ...(config as unknown as Record<string, unknown>) };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Only the most recent start intent matters — replace any queued one.
      const idx = this._sendQueue.findIndex((m) => m["type"] === "start");
      if (idx >= 0) this._sendQueue.splice(idx, 1);
      this._sendQueue.push(msg);
      this.connect();
    } else {
      this.sendJson(msg);
    }
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

  /** Subscribe to an already-running agent's event stream (for reconnection). */
  subscribeAgent(conversationId: string): void {
    const msg = { type: "subscribe_agent", conversation_id: conversationId };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      const idx = this._sendQueue.findIndex((m) => m["type"] === "subscribe_agent");
      if (idx >= 0) this._sendQueue.splice(idx, 1);
      this._sendQueue.push(msg);
      this.connect();
    } else {
      this.sendJson(msg);
    }
  }

  /** Subscribe to real-time repo events for a given repo. */
  subscribeEvents(repo: string): void {
    const msg = { type: "subscribe_events", repo };
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Only the most recent subscription matters — replace any queued one.
      const idx = this._sendQueue.findIndex((m) => m["type"] === "subscribe_events");
      if (idx >= 0) this._sendQueue.splice(idx, 1);
      this._sendQueue.push(msg);
      this.connect();
    } else {
      this.sendJson(msg);
    }
  }

  /** Permanently close the connection and disable auto-reconnect. */
  disconnect(): void {
    this._shouldReconnect = false;
    this._sendQueue.length = 0;
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setState("disconnected");
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _openConnection(): void {
    // Already connected or connecting — nothing to do.
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;

    // Cancel any pending reconnect timer so we don't double-connect.
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    this.setState("connecting");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/web/api/agent`;
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      this._reconnectAttempt = 0;
      this.setState("connected");
      // Drain the send queue — fire all buffered messages in order.
      const queued = this._sendQueue.splice(0);
      for (const msg of queued) {
        this.sendJson(msg);
      }
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
      this.ws = null;
      this.setState("disconnected");
      if (this._shouldReconnect) {
        // Exponential backoff capped at 30 s: 1 s, 2 s, 4 s, 8 s, 16 s, 30 s…
        const delay = Math.min(1_000 * 2 ** this._reconnectAttempt, 30_000);
        this._reconnectAttempt++;
        this._reconnectTimer = setTimeout(() => {
          this._reconnectTimer = null;
          if (this._shouldReconnect) this._openConnection();
        }, delay);
      }
    };

    ws.onerror = () => {
      // `onclose` always fires after `onerror` — reconnect logic lives there.
    };
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
      case "pr_created":
        this.callbacks.onPRCreated?.(msg as unknown as { pr_url: string; pr_number: number; pr_title: string; branch: string; base_branch: string; draft: boolean; user: string });
        break;
      case "repo_event":
        this.callbacks.onRepoEvent?.(msg as unknown as RepoEventData);
        break;
      case "agent_snapshot":
        this.callbacks.onSnapshot?.(msg as unknown as AgentSnapshotData);
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

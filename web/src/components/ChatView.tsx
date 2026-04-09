import { useCallback, useEffect, useMemo, useRef, useState, forwardRef, type ComponentPropsWithRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { useStore } from "../store";
import { ThinkingDeathStar, DeathStarSpinner } from "./DeathStarLoader";
import MessageBubble from "./MessageBubble";
import AgentStreamView from "./AgentStreamView";
import ActionBar from "./ActionBar";
import InputBar from "./InputBar";
import WorkflowPills from "./WorkflowPills";
import Starfield from "./Starfield";
import { ArrowDown, AlertTriangle, GitMerge } from "lucide-react";

export default function ChatView() {
  const activeConversation = useStore((s) => s.activeConversation);
  const sending = useStore((s) => s.sending);
  const compacting = useStore((s) => s.compacting);
  const agentStream = useStore((s) => s.agentStream);
  const streamingProgress = useStore((s) => s.streamingProgress);
  const selectedRepo = useStore((s) => s.selectedRepo);
  const persona = useStore((s) => s.persona);
  const repoContext = useStore((s) => s.repoContext);
  const sendMessage = useStore((s) => s.sendMessage);
  const setWorkflow = useStore((s) => s.setWorkflow);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [atBottom, setAtBottom] = useState(true);

  // Tracks explicit user intent to follow streaming output.  Set when the
  // user clicks "Follow along" and cleared when they scroll away manually.
  // Using a ref (not state) avoids re-render loops inside scroll callbacks.
  const followingRef = useRef(true);

  const conflictFiles = repoContext?.conflict_files ?? [];

  const conversationId = activeConversation?.id;

  // Reset atBottom when the conversation changes so the "Jump to latest"
  // button doesn't flash for one render frame after a key-triggered remount.
  // initialTopMostItemIndex guarantees the new Virtuoso starts at the bottom,
  // so pre-setting true keeps the UI consistent.
  //
  // We also schedule an explicit scroll-to-bottom after the first paint.
  // initialTopMostItemIndex positions the viewport, but Virtuoso's measured
  // item heights may shift once React finishes rendering markdown, syntax
  // highlighting, and agent blocks.  The delayed nudge catches those cases
  // so the user always sees the latest message on initial load.
  useEffect(() => {
    setAtBottom(true);
    followingRef.current = true;
    const t = setTimeout(() => {
      virtuosoRef.current?.scrollToIndex({ index: "LAST", align: "end", behavior: "auto" });
    }, 150);
    return () => clearTimeout(t);
  }, [conversationId]);
  const messages = activeConversation?.messages ?? [];
  const hasAgentBlocks = agentStream.blocks.length > 0;
  const isWaiting = sending && !hasAgentBlocks;

  // Build a virtual item list: messages + optional tail items (stream, waiting, compacting)
  const tailItems = useMemo(() => {
    const items: string[] = [];
    if (hasAgentBlocks) items.push("agent-stream");
    if (isWaiting) items.push("waiting");
    if (compacting && !isWaiting) items.push("compacting");
    return items;
  }, [hasAgentBlocks, isWaiting, compacting]);
  const totalCount = messages.length + tailItems.length;

  const scrollToBottom = useCallback(() => {
    // During active streaming, use instant scroll so the user lands at the
    // bottom immediately and followOutput can take over.  Smooth scroll
    // races against rapid content growth and often falls short of the
    // moving target, leaving the user stuck in limbo.
    const behavior = sending ? "auto" : "smooth";
    followingRef.current = true;
    // Use align: "end" so the *bottom* of the last item aligns with the
    // viewport bottom.  The default ("start") only brings the top of the
    // last item into view, leaving content below the fold when the item
    // is taller than the viewport (e.g. long agent responses).
    virtuosoRef.current?.scrollToIndex({ index: "LAST", align: "end", behavior });
  }, [sending]);

  const handleAtBottomChange = useCallback((bottom: boolean) => {
    setAtBottom(bottom);
    if (bottom) {
      // Arrived at the bottom — confirm follow intent so followOutput
      // continues to pin us there.
      followingRef.current = true;
    }
    // Note: we do NOT clear followingRef when bottom becomes false here
    // because Virtuoso briefly reports not-at-bottom during rapid content
    // growth even while following.  The ref is only cleared by the
    // isScrolling handler below when the user actively drags/flicks.
  }, []);

  // Clear follow intent when the user manually scrolls (drag / wheel / flick).
  // Virtuoso fires isScrolling=true on any scroll including programmatic ones,
  // but we only clear the ref when the user ends up NOT at the bottom — that
  // distinguishes a manual scroll-up from a programmatic snap-to-bottom.
  const handleIsScrolling = useCallback((scrolling: boolean) => {
    if (!scrolling && !atBottom) {
      followingRef.current = false;
    }
  }, [atBottom]);

  // Follow output keeps virtuoso pinned to the bottom while streaming.
  //
  // The callback receives Virtuoso's own `isAtBottom` check, but that can
  // lag behind rapid content growth (the single "agent-stream" tail item
  // gets taller without totalCount changing, so Virtuoso's height-change
  // detection isn't always timely).  We also honour `followingRef` — the
  // explicit user intent set by clicking "Follow along" — so we keep
  // scrolling even when Virtuoso briefly thinks we're not at the bottom.
  //
  // Return values:
  //   "auto"  — instant scroll (streaming: prevents stacking smooth animations)
  //   "smooth"— CSS-animated scroll (discrete events like message completion)
  //   false   — no auto-scroll (user is reading earlier messages)
  const isStreaming = sending && hasAgentBlocks;
  const followOutput = useCallback(
    (isAtBottom: boolean) => {
      if (!isAtBottom && !followingRef.current) return false;
      if (isStreaming) return "auto";
      if (sending || compacting) return "smooth";
      return false;
    },
    [isStreaming, sending, compacting],
  );

  // Safety-net: during streaming the "agent-stream" tail item grows
  // taller in-place without totalCount changing.  Virtuoso's followOutput
  // may not fire reliably for pure height growth, so we manually nudge the
  // scroll position whenever the block count changes and the user intends
  // to follow.
  const blockCount = agentStream.blocks.length;
  useEffect(() => {
    if (isStreaming && followingRef.current) {
      virtuosoRef.current?.scrollToIndex({ index: "LAST", behavior: "auto" });
    }
  }, [blockCount, isStreaming]);

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <Starfield />
      {/* Messages area */}
      {messages.length === 0 && !sending ? (
        <div className="relative z-10 min-w-0 flex-1 overflow-y-auto px-3 py-3 sm:px-4 sm:py-4">
          <EmptyState repo={selectedRepo!} personaName={persona.shortName} />
        </div>
      ) : (
        <div className="relative z-10 min-w-0 flex-1">
          <Virtuoso
            key={conversationId ?? "__new"}
            ref={virtuosoRef}
            initialTopMostItemIndex={totalCount > 0 ? totalCount - 1 : 0}
            totalCount={totalCount}
            atBottomStateChange={handleAtBottomChange}
            atBottomThreshold={150}
            followOutput={followOutput}
            isScrolling={handleIsScrolling}
            overscan={{ main: 600, reverse: 600 }}
            increaseViewportBy={{ top: 300, bottom: 300 }}
            className="h-full"
            components={{
              Scroller: ScrollerWithPadding,
              List: ListContainer,
            }}
            itemContent={(index) => {
              // Message items
              if (index < messages.length) {
                return (
                  <div className="pb-6">
                    <MessageBubble message={messages[index]!} index={index} />
                  </div>
                );
              }
              // Tail items (stream, waiting, compacting)
              const tailKey = tailItems[index - messages.length];
              if (tailKey === "agent-stream") {
                return (
                  <div className="pb-6 animate-fade-in">
                    <AgentStreamView blocks={agentStream.blocks} />
                    {streamingProgress && (
                      <p className="mt-2 text-xs text-text-muted animate-pulse">
                        {streamingProgress}
                      </p>
                    )}
                  </div>
                );
              }
              if (tailKey === "waiting") {
                return (
                  <div className="pb-6">
                    {streamingProgress && (
                      <p className="mb-2 text-xs text-text-muted animate-pulse">
                        {streamingProgress}
                      </p>
                    )}
                    <ThinkingDeathStar />
                  </div>
                );
              }
              if (tailKey === "compacting") {
                return (
                  <div className="pb-6 flex items-center gap-2 rounded-lg bg-bg-surface px-4 py-3 animate-fade-in">
                    <DeathStarSpinner />
                    <p className="text-xs text-text-muted animate-pulse">
                      Compacting conversation context...
                    </p>
                  </div>
                );
              }
              return null;
            }}
          />

          {/* Jump to latest — always visible when scrolled away from bottom */}
          {!atBottom && (
            <div className="absolute bottom-3 left-0 right-0 z-20 flex justify-center pointer-events-none">
              <button
                onClick={scrollToBottom}
                className={`pointer-events-auto flex items-center gap-1.5 rounded-full border border-border-subtle bg-bg-surface/95 px-3 py-1.5 text-xs font-medium text-text-secondary shadow-lg backdrop-blur transition-all duration-300 hover:bg-bg-surface hover:text-text-primary ${sending ? "animate-pulse" : ""}`}
              >
                <ArrowDown size={12} />
                {sending ? "Follow along" : "Jump to latest"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Conflict banner */}
      {conflictFiles.length > 0 && (
        <div className="border-t border-error/30 bg-error/5 px-4 py-2">
          <div className="mx-auto flex max-w-3xl items-start gap-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-error" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-error">
                Merge conflicts in {conflictFiles.length} file{conflictFiles.length > 1 ? "s" : ""}
              </p>
              <p className="mt-0.5 text-[11px] text-text-muted truncate">
                {conflictFiles.join(", ")}
              </p>
            </div>
            <button
              onClick={() => {
                setWorkflow("patch");
                const fileList = conflictFiles.map((f) => `- ${f}`).join("\n");
                sendMessage(
                  `Resolve the merge conflicts in the following files. For each file, read it, understand both sides of the conflict, choose the best resolution that preserves intended functionality from both branches, remove all conflict markers, and then save the file.\n\nConflicted files:\n${fileList}\n\nAfter resolving all conflicts, run \`git add\` on each resolved file.`,
                );
              }}
              disabled={sending}
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-error/20 px-3 py-1.5 text-xs font-medium text-error hover:bg-error/30 transition-colors disabled:opacity-50"
            >
              <GitMerge size={12} />
              Resolve Conflicts
            </button>
          </div>
        </div>
      )}

      {/* Input area — pb-safe provides env(safe-area-inset-bottom) clearance
           for the home indicator on iPad/iPhone, with a responsive floor
           (0.75 rem mobile, 1 rem sm+) so desktop spacing is unchanged. */}
      <div className="border-t border-border-subtle bg-bg-primary px-2 pt-2 pb-safe sm:px-4">
        <div className="mx-auto max-w-3xl min-w-0">
          <WorkflowPills />
          <ActionBar />
          <InputBar />
        </div>
      </div>
    </div>
  );
}

/* ── Custom Virtuoso sub-components ──────────────────────────── */

/** Outer scroll container — adds padding and disables horizontal scroll.
 *  Note: we intentionally omit `scroll-smooth` here — it would override
 *  Virtuoso's `followOutput: "auto"` (instant) at the CSS level, re-
 *  introducing the stacking-animation jank.  The manual "Jump to latest"
 *  button passes `behavior: "smooth"` explicitly, so that still animates. */
const ScrollerWithPadding = forwardRef<HTMLDivElement, ComponentPropsWithRef<"div">>(
  ({ className, style, ...props }, ref) => (
    <div
      {...props}
      ref={ref}
      style={{ ...style, overflowX: "hidden" }}
      className={`px-3 py-3 sm:px-4 sm:py-4 ${className ?? ""}`}
    />
  ),
);
ScrollerWithPadding.displayName = "ScrollerWithPadding";

/** Inner list wrapper — mirrors max-w-3xl + spacing. */
const ListContainer = forwardRef<HTMLDivElement, ComponentPropsWithRef<"div">>(
  ({ className, ...props }, ref) => (
    <div
      {...props}
      ref={ref}
      className={`mx-auto max-w-3xl ${className ?? ""}`}
    />
  ),
);
ListContainer.displayName = "ListContainer";

/* ── Empty state ─────────────────────────────────────────────── */

function EmptyState({ repo, personaName }: { repo: string; personaName: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <DeathStarSpinner size={64} className="mx-auto mb-4" />
        <h2 className="font-display text-2xl font-bold text-text-primary mb-2">
          {repo}
        </h2>
        <p className="text-sm text-text-muted max-w-md">
          Active persona: <span className="text-text-secondary">{personaName}</span>.
          <br />
          Ask anything about this codebase — chat, generate patches, or request reviews.
        </p>
      </div>
    </div>
  );
}

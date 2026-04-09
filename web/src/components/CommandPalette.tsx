import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { isModKey, modKeyLabel } from "@/lib/utils";

export interface CommandPaletteItem {
  id: string;
  label: string;
  sublabel?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  isCurrent?: boolean;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  items: CommandPaletteItem[];
  onSelect: (item: CommandPaletteItem) => void;
  /** The trigger key (without modifier) — pressing it again cycles to the next item */
  triggerKey?: string;
  title: string;
  placeholder?: string;
  emptyMessage?: string;
}

export default function CommandPalette({
  open,
  onClose,
  items,
  onSelect,
  triggerKey,
  title,
  placeholder = "Search...",
  emptyMessage = "No results",
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () =>
      items.filter((item) =>
        item.label.toLowerCase().includes(query.toLowerCase()) ||
        item.sublabel?.toLowerCase().includes(query.toLowerCase()),
      ),
    [items, query],
  );

  // Reset state when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      // Start with the current item selected, or 0
      const currentIdx = items.findIndex((i) => i.isCurrent);
      setActiveIndex(currentIdx >= 0 ? currentIdx : 0);
      // Focus input after a tick (dialog animation)
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open, items]);

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.children[activeIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  // Handle trigger key cycling (e.g. pressing Cmd+R again while palette is open)
  const handleTriggerCycle = useCallback(
    (e: KeyboardEvent) => {
      if (!open || !triggerKey) return;
      if (isModKey(e) && e.key.toLowerCase() === triggerKey.toLowerCase()) {
        e.preventDefault();
        setActiveIndex((prev) => {
          const list = filtered.length > 0 ? filtered : items;
          return list.length > 0 ? (prev + 1) % list.length : 0;
        });
      }
    },
    [open, triggerKey, filtered, items],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleTriggerCycle);
    return () => window.removeEventListener("keydown", handleTriggerCycle);
  }, [handleTriggerCycle]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (filtered.length > 0 ? (prev + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) => (filtered.length > 0 ? (prev - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[activeIndex]) {
        onSelect(filtered[activeIndex]);
      }
    }
  };

  // Reset active index when query changes
  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!open) return null;

  const modKey = modKeyLabel;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/40 supports-backdrop-filter:backdrop-blur-xs"
        onClick={onClose}
      />
      {/* Palette */}
      <div
        className="fixed left-1/2 top-[15%] z-[101] w-full max-w-md -translate-x-1/2 overflow-hidden rounded-xl border border-border-subtle bg-bg-surface shadow-2xl animate-in fade-in-0 zoom-in-95 duration-100"
        onKeyDown={handleKeyDown}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
          <span className="text-xs font-medium text-text-secondary">{title}</span>
          {triggerKey && (
            <span className="text-[10px] text-text-muted">
              {modKey}{triggerKey.toUpperCase()} to cycle
            </span>
          )}
        </div>

        {/* Search input */}
        <div className="border-b border-border-subtle px-3 py-2">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="w-full bg-transparent text-sm text-text-primary placeholder:text-text-muted focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-64 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-text-muted">{emptyMessage}</p>
          ) : (
            filtered.map((item, idx) => (
              <button
                key={item.id}
                onClick={() => onSelect(item)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  idx === activeIndex
                    ? "bg-accent-muted text-accent"
                    : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                }`}
              >
                {item.icon && <span className="shrink-0">{item.icon}</span>}
                <span className="flex flex-1 items-center gap-2 min-w-0">
                  <span className="truncate font-medium">{item.label}</span>
                  {item.sublabel && (
                    <span className="truncate text-xs text-text-muted font-normal">{item.sublabel}</span>
                  )}
                </span>
                {item.badge && <span className="shrink-0">{item.badge}</span>}
                {item.isCurrent && (
                  <span className="shrink-0 text-[10px] text-accent font-medium">current</span>
                )}
              </button>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center gap-3 border-t border-border-subtle px-4 py-2">
          <span className="flex items-center gap-1 text-[10px] text-text-muted">
            <kbd className="rounded border border-border-subtle bg-bg-primary px-1 py-0.5 font-mono text-[10px]">&uarr;&darr;</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1 text-[10px] text-text-muted">
            <kbd className="rounded border border-border-subtle bg-bg-primary px-1 py-0.5 font-mono text-[10px]">&crarr;</kbd>
            select
          </span>
          <span className="flex items-center gap-1 text-[10px] text-text-muted">
            <kbd className="rounded border border-border-subtle bg-bg-primary px-1 py-0.5 font-mono text-[10px]">esc</kbd>
            close
          </span>
        </div>
      </div>
    </>
  );
}

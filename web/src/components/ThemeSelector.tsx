import { useState, useRef, useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { themes } from "../themes";
import { useStore } from "../store";
import type { Theme } from "../themes";

export default function ThemeSelector() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const theme = useStore((s) => s.theme);
  const setTheme = useStore((s) => s.setTheme);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs transition-colors hover:bg-bg-hover"
        title={theme.name}
      >
        <span
          className="h-3 w-3 rounded-full ring-1 ring-white/20"
          style={{ background: theme.swatch }}
        />
        <ChevronDown size={10} className="text-text-muted" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-lg border border-border-subtle bg-bg-surface p-1 shadow-xl animate-fade-in">
          {themes.map((t) => (
            <ThemeOption
              key={t.id}
              theme={t}
              selected={t.id === theme.id}
              onSelect={() => {
                setTheme(t);
                setOpen(false);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ThemeOption({
  theme,
  selected,
  onSelect,
}: {
  theme: Theme;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors ${
        selected ? "bg-bg-hover" : "hover:bg-bg-hover"
      }`}
    >
      <span
        className="h-4 w-4 shrink-0 rounded-full ring-1 ring-white/20"
        style={{ background: theme.swatch }}
      />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-text-primary">{theme.name}</p>
        <p className="text-[10px] text-text-muted truncate italic">
          {theme.subtitle}
        </p>
      </div>
      {selected && (
        <div
          className="h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: theme.swatch }}
        />
      )}
    </button>
  );
}

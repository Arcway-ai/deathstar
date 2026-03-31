import { useState, useRef, useEffect } from "react";
import {
  Paintbrush,
  Layers,
  Shield,
  Container,
  Database,
  PenTool,
  Building2,
  ScanSearch,
  ChevronDown,
} from "lucide-react";
import { personas } from "../personas";
import { useStore } from "../store";
import type { Persona } from "../types";

const iconMap: Record<string, typeof Paintbrush> = {
  Paintbrush,
  Layers,
  Shield,
  Container,
  Database,
  PenTool,
  Building2,
  ScanSearch,
};

export default function PersonaSelector() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const persona = useStore((s) => s.persona);
  const setPersona = useStore((s) => s.setPersona);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const Icon = iconMap[persona.icon] ?? Layers;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors hover:bg-bg-hover"
        style={{ color: persona.color }}
      >
        <Icon size={14} />
        <span className="hidden sm:inline">{persona.shortName}</span>
        <ChevronDown size={12} className="text-text-muted" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-border-subtle bg-bg-surface p-1 shadow-xl animate-fade-in">
          {personas.map((p) => (
            <PersonaOption
              key={p.id}
              persona={p}
              selected={p.id === persona.id}
              onSelect={() => {
                setPersona(p);
                setOpen(false);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PersonaOption({
  persona,
  selected,
  onSelect,
}: {
  persona: Persona;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = iconMap[persona.icon] ?? Layers;

  return (
    <button
      onClick={onSelect}
      className={`flex w-full items-start gap-2.5 rounded-md px-3 py-2 text-left transition-colors ${
        selected ? "bg-bg-hover" : "hover:bg-bg-hover"
      }`}
    >
      <div
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: `${persona.color}15`, color: persona.color }}
      >
        <Icon size={14} />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-text-primary">{persona.name}</p>
        <p className="text-[10px] text-text-muted leading-relaxed">
          {persona.description}
        </p>
      </div>
      {selected && (
        <div
          className="ml-auto mt-1 h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: persona.color }}
        />
      )}
    </button>
  );
}

import { useEffect, useState } from "react";

/**
 * Kyber crystal colors — canonical lightsaber blade hues.
 * Each entry: [blade color, glow color (lower opacity for outer glow)]
 */
const KYBER_CRYSTALS: [string, string][] = [
  ["#4a9eff", "rgba(74,158,255,0.6)"],   // Blue — Jedi Guardian
  ["#34d399", "rgba(52,211,153,0.6)"],    // Green — Jedi Consular
  ["#ff4444", "rgba(255,68,68,0.6)"],     // Red — Sith
  ["#c084fc", "rgba(192,132,252,0.6)"],   // Purple — Mace Windu
  ["#fbbf24", "rgba(251,191,36,0.6)"],    // Yellow — Jedi Sentinel
  ["#ffffff", "rgba(255,255,255,0.5)"],    // White — Ahsoka (purified)
  ["#fb923c", "rgba(251,146,60,0.6)"],    // Orange — rare
];

function randomCrystal(exclude?: number): number {
  let next: number;
  do {
    next = Math.floor(Math.random() * KYBER_CRYSTALS.length);
  } while (next === exclude);
  return next;
}

export default function LightsaberIndicator({ className = "" }: { className?: string }) {
  const [crystalIdx, setCrystalIdx] = useState(() => randomCrystal());

  useEffect(() => {
    const interval = setInterval(() => {
      setCrystalIdx((prev) => randomCrystal(prev));
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const blade = KYBER_CRYSTALS[crystalIdx]?.[0] ?? "#4a9eff";
  const glow = KYBER_CRYSTALS[crystalIdx]?.[1] ?? "rgba(74,158,255,0.6)";

  return (
    <span className={`inline-flex items-center gap-0 align-text-bottom ${className}`}>
      {/* Hilt (horizontal: pommel → grip → emitter → blade) */}
      <svg width="14" height="8" viewBox="0 0 14 8" className="shrink-0">
        {/* Pommel (left cap) */}
        <rect x="0" y="1" width="2.5" height="6" rx="1" fill="#3d4f65" />
        {/* Grip */}
        <rect x="2" y="2" width="7" height="4" rx="0.5" fill="#2a3444" />
        {/* Grip ridges */}
        <rect x="3.5" y="2" width="0.8" height="4" rx="0.3" fill="#4a5568" />
        <rect x="5.5" y="2" width="0.8" height="4" rx="0.3" fill="#4a5568" />
        <rect x="7.5" y="2" width="0.8" height="4" rx="0.3" fill="#4a5568" />
        {/* Emitter shroud */}
        <rect x="9" y="1" width="3.5" height="6" rx="0.5" fill="#4a5568" />
        {/* Emitter nozzle */}
        <rect x="12" y="2" width="2" height="4" rx="0.5" fill="#64748b" />
      </svg>
      {/* Blade */}
      <span
        className="lightsaber-blade"
        style={{
          "--ls-blade": blade,
          "--ls-glow": glow,
        } as React.CSSProperties}
      />
    </span>
  );
}

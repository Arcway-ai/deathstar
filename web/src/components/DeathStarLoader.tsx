/**
 * Animated Death Star + TIE fighter loading indicators.
 *
 * - <DeathStarSpinner />  — 3D rotating Death Star (thinking/loading)
 * - <TIEFighterLoader />  — TIE fighters flying across the screen
 */

import { useEffect, useState } from "react";

/* ── 3D Death Star Spinner ────────────────────────────────────────── */

export function DeathStarSpinner({ size = 48, className = "" }: { size?: number; className?: string }) {
  return (
    <div className={`relative ${className}`} style={{ width: size, height: size }}>
      {/* Glow pulse behind the sphere */}
      <div
        className="absolute inset-0 rounded-full animate-[ds-glow_2s_ease-in-out_infinite]"
        style={{
          background: "radial-gradient(circle, rgba(74,158,255,0.15) 0%, transparent 70%)",
          transform: "scale(1.4)",
        }}
      />
      {/* SVG Death Star with CSS rotation */}
      <svg
        viewBox="0 0 100 100"
        className="animate-[ds-rotate_4s_linear_infinite]"
        style={{ width: size, height: size, filter: "drop-shadow(0 0 8px rgba(74,158,255,0.3))" }}
      >
        <defs>
          <radialGradient id="ds-grad" cx="38%" cy="35%" r="55%">
            <stop offset="0%" stopColor="#3d4f65" />
            <stop offset="60%" stopColor="#1c2333" />
            <stop offset="100%" stopColor="#0c1018" />
          </radialGradient>
          <radialGradient id="ds-dish" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#4a9eff" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          {/* Rotating surface pattern — gives illusion of 3D spin */}
          <clipPath id="ds-clip">
            <circle cx="50" cy="50" r="44" />
          </clipPath>
        </defs>

        {/* Main sphere */}
        <circle cx="50" cy="50" r="44" fill="url(#ds-grad)" stroke="#2a3444" strokeWidth="1.5" />

        {/* Surface lines that rotate for 3D effect */}
        <g clipPath="url(#ds-clip)" className="animate-[ds-surface_8s_linear_infinite]">
          <line x1="20" y1="0" x2="20" y2="100" stroke="#1e2736" strokeWidth="0.6" opacity="0.5" />
          <line x1="35" y1="0" x2="35" y2="100" stroke="#1e2736" strokeWidth="0.8" opacity="0.6" />
          <line x1="50" y1="0" x2="50" y2="100" stroke="#1e2736" strokeWidth="0.8" opacity="0.6" />
          <line x1="65" y1="0" x2="65" y2="100" stroke="#1e2736" strokeWidth="0.8" opacity="0.6" />
          <line x1="80" y1="0" x2="80" y2="100" stroke="#1e2736" strokeWidth="0.6" opacity="0.5" />
        </g>

        {/* Equatorial trench */}
        <ellipse cx="50" cy="52" rx="44" ry="5" fill="none" stroke="#141a24" strokeWidth="3" />
        <ellipse cx="50" cy="52" rx="44" ry="5" fill="none" stroke="#2a3444" strokeWidth="1" />

        {/* Superlaser dish */}
        <circle cx="35" cy="30" r="12" fill="none" stroke="#2a3444" strokeWidth="1.2" />
        <circle cx="35" cy="30" r="7" fill="url(#ds-dish)" opacity="0.5" />
        <circle cx="35" cy="30" r="3" fill="#4a9eff" opacity="0.9" className="animate-[ds-laser_2s_ease-in-out_infinite]" />

        {/* Highlight */}
        <ellipse cx="36" cy="22" rx="14" ry="6" fill="white" opacity="0.04" transform="rotate(-15 36 22)" />
      </svg>
    </div>
  );
}

/* ── TIE Fighter Loader ───────────────────────────────────────────── */

function TIEFighter({ style, className = "" }: { style?: React.CSSProperties; className?: string }) {
  return (
    <svg viewBox="0 0 40 30" className={className} style={{ width: 24, height: 18, ...style }}>
      {/* Left wing */}
      <polygon points="2,1 6,1 6,29 2,29" fill="#2a3444" stroke="#3d4f65" strokeWidth="0.5" />
      {/* Right wing */}
      <polygon points="34,1 38,1 38,29 34,29" fill="#2a3444" stroke="#3d4f65" strokeWidth="0.5" />
      {/* Wing struts */}
      <line x1="6" y1="15" x2="14" y2="15" stroke="#3d4f65" strokeWidth="1.5" />
      <line x1="26" y1="15" x2="34" y2="15" stroke="#3d4f65" strokeWidth="1.5" />
      {/* Cockpit */}
      <circle cx="20" cy="15" r="6" fill="#1c2333" stroke="#3d4f65" strokeWidth="1" />
      {/* Window */}
      <circle cx="20" cy="15" r="2.5" fill="#4a9eff" opacity="0.7" />
    </svg>
  );
}

export function TIEFighterLoader({ text = "Loading" }: { text?: string }) {
  const [dots, setDots] = useState("");

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "" : d + "."));
    }, 400);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col items-center gap-4 py-8">
      {/* TIE fighter formation */}
      <div className="relative h-12 w-48 overflow-hidden">
        {/* TIE 1 — lead */}
        <div className="absolute animate-[tie-fly-1_3s_ease-in-out_infinite]" style={{ top: 8 }}>
          <TIEFighter />
        </div>
        {/* TIE 2 — left wing */}
        <div className="absolute animate-[tie-fly-2_3s_ease-in-out_infinite]" style={{ top: 0 }}>
          <TIEFighter style={{ opacity: 0.6 }} />
        </div>
        {/* TIE 3 — right wing */}
        <div className="absolute animate-[tie-fly-3_3s_ease-in-out_infinite]" style={{ top: 20 }}>
          <TIEFighter style={{ opacity: 0.6 }} />
        </div>
        {/* Engine trails */}
        <div className="absolute h-[1px] animate-[tie-trail-1_3s_ease-in-out_infinite]" style={{ top: 16, background: "linear-gradient(to right, transparent, rgba(74,158,255,0.4), transparent)", width: 40 }} />
        <div className="absolute h-[1px] animate-[tie-trail-2_3s_ease-in-out_infinite]" style={{ top: 8, background: "linear-gradient(to right, transparent, rgba(74,158,255,0.3), transparent)", width: 30 }} />
        <div className="absolute h-[1px] animate-[tie-trail-3_3s_ease-in-out_infinite]" style={{ top: 28, background: "linear-gradient(to right, transparent, rgba(74,158,255,0.3), transparent)", width: 30 }} />
      </div>
      <span className="text-xs text-text-muted font-mono w-20 text-center">{text}{dots}</span>
    </div>
  );
}

/* ── Thinking Death Star (replaces the simple dots in ChatView) ──── */

export function ThinkingDeathStar() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const fmt = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  return (
    <div className="flex items-center gap-3 py-3 px-4 animate-fade-in">
      <DeathStarSpinner size={28} />
      <div className="flex flex-col">
        <span className="text-xs text-text-muted">Analyzing target</span>
        <span className="text-[10px] text-text-muted font-mono">{fmt}</span>
      </div>
    </div>
  );
}

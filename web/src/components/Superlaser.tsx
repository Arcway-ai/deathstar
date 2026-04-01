import { useEffect, useState } from "react";
import { useStore } from "../store";

/**
 * Full-viewport Death Star superlaser animation overlay.
 * Fires a green beam from a charging point with explosion flash.
 */
export default function Superlaser() {
  const firing = useStore((s) => s.superlaserFiring);
  const stopSuperlaser = useStore((s) => s.stopSuperlaser);
  const [phase, setPhase] = useState<"idle" | "charge" | "fire" | "flash" | "done">("idle");

  useEffect(() => {
    if (!firing) {
      setPhase("idle");
      return;
    }

    setPhase("charge");
    const t1 = setTimeout(() => setPhase("fire"), 800);
    const t2 = setTimeout(() => setPhase("flash"), 1400);
    const t3 = setTimeout(() => {
      setPhase("done");
      stopSuperlaser();
    }, 2600);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [firing, stopSuperlaser]);

  if (phase === "idle" || phase === "done") return null;

  return (
    <div className="superlaser-overlay" aria-hidden>
      {/* Charging orb */}
      <div className={`superlaser-orb ${phase === "charge" ? "charging" : phase === "fire" || phase === "flash" ? "charged" : ""}`} />

      {/* Converging beams during charge */}
      {phase === "charge" && (
        <>
          <div className="superlaser-converge superlaser-converge-1" />
          <div className="superlaser-converge superlaser-converge-2" />
          <div className="superlaser-converge superlaser-converge-3" />
          <div className="superlaser-converge superlaser-converge-4" />
        </>
      )}

      {/* Main beam */}
      {(phase === "fire" || phase === "flash") && (
        <div className="superlaser-beam" />
      )}

      {/* Impact explosion */}
      {phase === "flash" && (
        <>
          <div className="superlaser-impact" />
          <div className="superlaser-flash" />
        </>
      )}
    </div>
  );
}

/** Compact button for the TopBar — fires the superlaser to compress context. */
export function SuperlaserButton() {
  const fireSuperlaser = useStore((s) => s.fireSuperlaser);
  const firing = useStore((s) => s.superlaserFiring);
  const compacting = useStore((s) => s.compacting);
  const conversationId = useStore((s) => s.conversationId);
  const sending = useStore((s) => s.sending);

  return (
    <button
      onClick={fireSuperlaser}
      disabled={firing || compacting || sending || !conversationId}
      className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-success transition-colors disabled:opacity-30"
      title="Compact conversation context"
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        {/* Death Star silhouette */}
        <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.2" />
        {/* Equatorial trench */}
        <line x1="1" y1="8" x2="15" y2="8" stroke="currentColor" strokeWidth="0.6" opacity="0.5" />
        {/* Superlaser dish */}
        <circle cx="5.5" cy="5.5" r="2.5" stroke="currentColor" strokeWidth="0.8" fill="none" />
        <circle cx="5.5" cy="5.5" r="0.8" fill="currentColor" />
      </svg>
    </button>
  );
}

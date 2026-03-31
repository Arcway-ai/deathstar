import { useEffect, useMemo, useState } from "react";

/**
 * Subtle starfield background — sparse, gently twinkling points of light
 * with occasional TIE fighter flybys.
 */

interface Star {
  x: number;     // % from left
  y: number;     // % from top
  size: number;  // px
  dur: number;   // twinkle duration (s)
  delay: number; // animation delay (s)
  minO: number;  // min opacity
  maxO: number;  // max opacity
}

interface Flyby {
  id: number;
  y: number;        // % from top
  duration: number;  // seconds to cross the screen
  direction: "ltr" | "rtl";
  scale: number;     // 0.5–1.2 for depth variety
  opacity: number;
}

// Deterministic pseudo-random based on seed
function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 16807 + 0) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function generateStars(count: number): Star[] {
  const rand = seededRandom(42);
  const stars: Star[] = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: rand() * 100,
      y: rand() * 100,
      size: rand() < 0.85 ? 1 : rand() < 0.95 ? 1.5 : 2,
      dur: 3 + rand() * 6,      // 3–9s twinkle cycle
      delay: rand() * -8,        // stagger so they don't all sync
      minO: 0.08 + rand() * 0.12, // barely visible at dimmest
      maxO: 0.3 + rand() * 0.35,  // gentle peak
    });
  }
  return stars;
}

let _flybyId = 0;

function TIEFighterSVG({ scale = 1 }: { scale?: number }) {
  const w = 24 * scale;
  const h = 18 * scale;
  return (
    <svg viewBox="0 0 40 30" style={{ width: w, height: h }}>
      <polygon points="2,1 6,1 6,29 2,29" fill="#2a3444" stroke="#3d4f65" strokeWidth="0.5" />
      <polygon points="34,1 38,1 38,29 34,29" fill="#2a3444" stroke="#3d4f65" strokeWidth="0.5" />
      <line x1="6" y1="15" x2="14" y2="15" stroke="#3d4f65" strokeWidth="1.5" />
      <line x1="26" y1="15" x2="34" y2="15" stroke="#3d4f65" strokeWidth="1.5" />
      <circle cx="20" cy="15" r="6" fill="#1c2333" stroke="#3d4f65" strokeWidth="1" />
      <circle cx="20" cy="15" r="2.5" fill="#4a9eff" opacity="0.7" />
    </svg>
  );
}

function FlybyTIE({ flyby, onDone }: { flyby: Flyby; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, flyby.duration * 1000);
    return () => clearTimeout(timer);
  }, [flyby.duration, onDone]);

  const isLTR = flyby.direction === "ltr";

  return (
    <div
      className="tie-flyby"
      style={{
        top: `${flyby.y}%`,
        opacity: flyby.opacity,
        animationDuration: `${flyby.duration}s`,
        animationName: isLTR ? "tie-flyby-ltr" : "tie-flyby-rtl",
        transform: isLTR ? "" : "scaleX(-1)",
      }}
    >
      {/* Engine trail */}
      <div
        className="tie-trail"
        style={{
          width: 30 * flyby.scale,
          [isLTR ? "right" : "left"]: "100%",
          transform: isLTR ? "" : "scaleX(-1)",
        }}
      />
      <TIEFighterSVG scale={flyby.scale} />
    </div>
  );
}

export default function Starfield() {
  const stars = useMemo(() => generateStars(80), []);
  const [flybys, setFlybys] = useState<Flyby[]>([]);

  useEffect(() => {
    function scheduleNext() {
      // Random interval: 8–25 seconds between flybys
      const delay = (8 + Math.random() * 17) * 1000;
      return setTimeout(() => {
        const flyby: Flyby = {
          id: ++_flybyId,
          y: 10 + Math.random() * 75,
          duration: 4 + Math.random() * 5,
          direction: Math.random() > 0.5 ? "ltr" : "rtl",
          scale: 1.0 + Math.random() * 0.8,
          opacity: 0.3 + Math.random() * 0.3,
        };
        setFlybys((prev) => [...prev, flyby]);
        timerRef = scheduleNext();
      }, delay);
    }

    let timerRef = scheduleNext();
    return () => clearTimeout(timerRef);
  }, []);

  const removeFlyby = (id: number) => {
    setFlybys((prev) => prev.filter((f) => f.id !== id));
  };

  return (
    <div className="starfield" aria-hidden="true">
      {stars.map((star, i) => (
        <div
          key={i}
          className="star"
          style={{
            left: `${star.x}%`,
            top: `${star.y}%`,
            width: `${star.size}px`,
            height: `${star.size}px`,
            "--dur": `${star.dur}s`,
            "--delay": `${star.delay}s`,
            "--min-o": star.minO,
            "--max-o": star.maxO,
          } as React.CSSProperties}
        />
      ))}
      {flybys.map((flyby) => (
        <FlybyTIE key={flyby.id} flyby={flyby} onDone={() => removeFlyby(flyby.id)} />
      ))}
    </div>
  );
}

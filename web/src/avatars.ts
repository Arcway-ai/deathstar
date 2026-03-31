/**
 * Lego-style minifigure avatar generator.
 *
 * Generates generic block-figure SVGs with character-themed colors.
 * No copyrighted likenesses — just colored geometric minifigures.
 */

type CharacterTheme = {
  head: string;    // head/skin color
  body: string;    // torso color
  body2: string;   // torso accent/belt
  legs: string;    // leg color
  accent: string;  // detail color (eyes, emblem)
};

const CHARACTER_THEMES: Record<string, CharacterTheme> = {
  // ── Dark Side ──────────────────────────────────────────
  "Darth Vader":          { head: "#1a1a1a", body: "#222222", body2: "#444444", legs: "#1a1a1a", accent: "#ff3333" },
  "Emperor Palpatine":    { head: "#8e8e7a", body: "#1a1a2e", body2: "#2d1854", legs: "#1a1a2e", accent: "#9b59b6" },
  "Darth Maul":           { head: "#cc0000", body: "#1a1a1a", body2: "#333333", legs: "#1a1a1a", accent: "#ffcc00" },
  "Count Dooku":          { head: "#d4a574", body: "#5d3a1a", body2: "#3a2010", legs: "#2c1810", accent: "#ff3333" },
  "Kylo Ren":             { head: "#1a1a1a", body: "#0d0d0d", body2: "#333333", legs: "#1a1a1a", accent: "#ff4444" },
  "General Grievous":     { head: "#e0e0e0", body: "#666666", body2: "#444444", legs: "#555555", accent: "#ffcc00" },
  "Grand Moff Tarkin":    { head: "#d4a574", body: "#4a5568", body2: "#2d3748", legs: "#1a202c", accent: "#a0aec0" },
  "Grand Admiral Thrawn": { head: "#4a80b4", body: "#e8e8e8", body2: "#c0c0c0", legs: "#e8e8e8", accent: "#ff3333" },
  "Jabba the Hutt":       { head: "#7d8a2e", body: "#6b7a1e", body2: "#4a5d23", legs: "#4a5d23", accent: "#ffcc00" },
  "Asajj Ventress":       { head: "#e8e0d0", body: "#1a1a2e", body2: "#333344", legs: "#1a1a2e", accent: "#ff3333" },

  // ── Jedi ───────────────────────────────────────────────
  "Luke Skywalker":       { head: "#f0c8a0", body: "#222222", body2: "#333333", legs: "#1a1a1a", accent: "#4a9eff" },
  "Obi-Wan Kenobi":       { head: "#f0c8a0", body: "#c4a46c", body2: "#a08050", legs: "#8b7355", accent: "#4a9eff" },
  "Yoda":                 { head: "#6b8e23", body: "#8b7355", body2: "#6b5b3a", legs: "#8b7355", accent: "#27ae60" },
  "Mace Windu":           { head: "#8b6914", body: "#c4a46c", body2: "#a08050", legs: "#8b7355", accent: "#9b59b6" },
  "Ahsoka Tano":          { head: "#e67e22", body: "#2c3e50", body2: "#34495e", legs: "#2c3e50", accent: "#e8e8e8" },
  "Anakin Skywalker":     { head: "#f0c8a0", body: "#2c1810", body2: "#1a1a1a", legs: "#2c1810", accent: "#4a9eff" },
  "Qui-Gon Jinn":         { head: "#f0c8a0", body: "#c4a46c", body2: "#a08050", legs: "#6b5b3a", accent: "#27ae60" },
  "Rey Skywalker":        { head: "#f0c8a0", body: "#d4c4a0", body2: "#c4a46c", legs: "#a08050", accent: "#ffd700" },
  "Kanan Jarrus":         { head: "#d4a574", body: "#2e86c1", body2: "#1a5276", legs: "#2c3e50", accent: "#4a9eff" },
  "Kit Fisto":            { head: "#1abc9c", body: "#c4a46c", body2: "#a08050", legs: "#8b7355", accent: "#27ae60" },
  "Plo Koon":             { head: "#d4a060", body: "#2c3e50", body2: "#1a252f", legs: "#2c3e50", accent: "#4a9eff" },
  "Barriss Offee":        { head: "#e8d8b0", body: "#1e8449", body2: "#145a32", legs: "#1e8449", accent: "#4a9eff" },

  // ── Rebels / Resistance ────────────────────────────────
  "Princess Leia":        { head: "#f0c8a0", body: "#ffffff", body2: "#e0e0e0", legs: "#ffffff", accent: "#a569bd" },
  "Han Solo":             { head: "#f0c8a0", body: "#e8e8e8", body2: "#444444", legs: "#2c3e50", accent: "#c0392b" },
  "Chewbacca":            { head: "#8d6e63", body: "#6d4c41", body2: "#5d4037", legs: "#6d4c41", accent: "#d7ccc8" },
  "Lando Calrissian":     { head: "#8b6914", body: "#1a237e", body2: "#0d1642", legs: "#1a237e", accent: "#ffc107" },
  "Finn":                 { head: "#8b6914", body: "#5d4037", body2: "#3e2723", legs: "#2c3e50", accent: "#e67e22" },
  "Poe Dameron":          { head: "#d4a574", body: "#e65100", body2: "#bf360c", legs: "#2c3e50", accent: "#ff8f00" },
  "Padmé Amidala":        { head: "#f0c8a0", body: "#4a148c", body2: "#6a1b9a", legs: "#4a148c", accent: "#ce93d8" },
  "Cassian Andor":        { head: "#d4a574", body: "#37474f", body2: "#263238", legs: "#37474f", accent: "#78909c" },
  "Jyn Erso":             { head: "#f0c8a0", body: "#4e342e", body2: "#3e2723", legs: "#4e342e", accent: "#8d6e63" },
  "Admiral Ackbar":       { head: "#c0785a", body: "#e8e8e8", body2: "#c0c0c0", legs: "#e8e8e8", accent: "#b71c1c" },
  "Wedge Antilles":       { head: "#f0c8a0", body: "#e65100", body2: "#bf360c", legs: "#e8e8e8", accent: "#ff6d00" },
  "Sabine Wren":          { head: "#d4a574", body: "#e91e63", body2: "#ff6f00", legs: "#4a148c", accent: "#ffeb3b" },
  "Hera Syndulla":        { head: "#4caf50", body: "#5d4037", body2: "#3e2723", legs: "#5d4037", accent: "#ff8f00" },
  "Saw Gerrera":          { head: "#8b6914", body: "#5d4037", body2: "#3e2723", legs: "#5d4037", accent: "#ff8f00" },
  "Mon Mothma":           { head: "#f0c8a0", body: "#e8eaf6", body2: "#c5cae9", legs: "#e8eaf6", accent: "#3f51b5" },
  "Bail Organa":          { head: "#d4a574", body: "#1a237e", body2: "#0d1642", legs: "#1a237e", accent: "#7986cb" },
  "Captain Rex":          { head: "#e8e8e8", body: "#1565c0", body2: "#0d47a1", legs: "#e8e8e8", accent: "#42a5f5" },

  // ── Droids ─────────────────────────────────────────────
  "R2-D2":                { head: "#e0e0e0", body: "#e0e0e0", body2: "#1565c0", legs: "#e0e0e0", accent: "#e53935" },
  "C-3PO":                { head: "#fdd835", body: "#f9a825", body2: "#f57f17", legs: "#f9a825", accent: "#5d4037" },
  "K-2SO":                { head: "#424242", body: "#333333", body2: "#212121", legs: "#333333", accent: "#ffcc00" },

  // ── Mandalorians / Bounty Hunters ──────────────────────
  "Boba Fett":            { head: "#558b2f", body: "#558b2f", body2: "#33691e", legs: "#1b5e20", accent: "#ff3333" },
  "Jango Fett":           { head: "#5c6bc0", body: "#5c6bc0", body2: "#3949ab", legs: "#283593", accent: "#e8eaf6" },
  "Din Djarin":           { head: "#9e9e9e", body: "#616161", body2: "#424242", legs: "#616161", accent: "#bdbdbd" },
  "Grogu":                { head: "#66bb6a", body: "#8d6e63", body2: "#6d4c41", legs: "#795548", accent: "#1b5e20" },

  // ── Other ──────────────────────────────────────────────
  "Chirrut Îmwe":         { head: "#d4a574", body: "#8d6e63", body2: "#6d4c41", legs: "#5d4037", accent: "#e0e0e0" },
  "Nien Nunb":            { head: "#c0785a", body: "#5d4037", body2: "#3e2723", legs: "#5d4037", accent: "#ffccbc" },
};

function getTheme(name: string): CharacterTheme {
  if (CHARACTER_THEMES[name]) return CHARACTER_THEMES[name];

  // Fallback: deterministic color from name hash
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const h = Math.abs(hash) % 360;
  return {
    head: `hsl(${h}, 30%, 70%)`,
    body: `hsl(${h}, 40%, 35%)`,
    body2: `hsl(${h}, 40%, 25%)`,
    legs: `hsl(${h}, 40%, 30%)`,
    accent: `hsl(${(h + 180) % 360}, 50%, 60%)`,
  };
}

/**
 * Generates a lego-style minifigure SVG as a data URI.
 */
export function characterAvatarUrl(name: string): string {
  const t = getTheme(name);

  // Each id must be unique per SVG instance — use a hash of the name
  let h = 0;
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  const uid = Math.abs(h).toString(36);

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
  <defs>
    <linearGradient id="b${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${t.body}"/>
      <stop offset="100%" stop-color="${t.body2}"/>
    </linearGradient>
  </defs>
  <!-- Head stud -->
  <rect x="17" y="3" width="6" height="3" rx="1" fill="${t.head}" opacity="0.8"/>
  <!-- Head -->
  <rect x="12" y="6" width="16" height="13" rx="3" fill="${t.head}"/>
  <!-- Eyes -->
  <circle cx="16.5" cy="12" r="1.5" fill="${t.accent}"/>
  <circle cx="23.5" cy="12" r="1.5" fill="${t.accent}"/>
  <!-- Eye shine -->
  <circle cx="17" cy="11.5" r="0.5" fill="white" opacity="0.7"/>
  <circle cx="24" cy="11.5" r="0.5" fill="white" opacity="0.7"/>
  <!-- Torso -->
  <rect x="10" y="19" width="20" height="11" rx="2" fill="url(#b${uid})"/>
  <!-- Belt/detail line -->
  <rect x="10" y="26" width="20" height="2" fill="${t.body2}" opacity="0.6"/>
  <!-- Emblem dot -->
  <circle cx="20" cy="23" r="1.5" fill="${t.accent}" opacity="0.5"/>
  <!-- Left arm -->
  <rect x="6" y="19" width="5" height="9" rx="2" fill="${t.body}"/>
  <!-- Right arm -->
  <rect x="29" y="19" width="5" height="9" rx="2" fill="${t.body}"/>
  <!-- Left leg -->
  <rect x="12" y="30" width="7" height="8" rx="1.5" fill="${t.legs}"/>
  <!-- Right leg -->
  <rect x="21" y="30" width="7" height="8" rx="1.5" fill="${t.legs}"/>
  <!-- Leg separator -->
  <line x1="20" y1="30" x2="20" y2="37" stroke="${t.body2}" stroke-width="0.5" opacity="0.4"/>
</svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/**
 * Check if a commit author is a DeathStar character (by email domain).
 */
export function isDeathStarAuthor(email?: string): boolean {
  return !!email && email.endsWith("@deathstar.ai");
}

export interface Theme {
  id: string;
  name: string;
  subtitle: string;
  /** CSS color for the theme selector dot */
  swatch: string;
  /** CSS custom property overrides applied to :root */
  vars: Record<string, string>;
}

export const themes: Theme[] = [
  {
    id: "obiwan",
    name: "Obi-Wan Kenobi",
    subtitle: "Hello there",
    swatch: "#4a9eff",
    vars: {
      "--color-accent": "#4a9eff",
      "--color-accent-hover": "#6cb4ff",
      "--color-accent-muted": "#4a9eff26",
      "--color-bg-deep": "#06080c",
      "--color-bg-primary": "#0c1018",
      "--color-bg-surface": "#141a24",
      "--color-bg-elevated": "#1c2333",
      "--color-bg-hover": "#232d3f",
      "--color-border-subtle": "#1e2736",
      "--color-border-default": "#2a3444",
      "--color-border-strong": "#3d4f65",
    },
  },
  {
    id: "luke",
    name: "Luke Skywalker",
    subtitle: "I am a Jedi, like my father before me",
    swatch: "#34d399",
    vars: {
      "--color-accent": "#34d399",
      "--color-accent-hover": "#6ee7b7",
      "--color-accent-muted": "#34d39926",
      "--color-bg-deep": "#040a06",
      "--color-bg-primary": "#08120c",
      "--color-bg-surface": "#101c14",
      "--color-bg-elevated": "#182a1e",
      "--color-bg-hover": "#20362a",
      "--color-border-subtle": "#1a2e22",
      "--color-border-default": "#263e32",
      "--color-border-strong": "#385848",
    },
  },
  {
    id: "mace",
    name: "Mace Windu",
    subtitle: "This party's over",
    swatch: "#c084fc",
    vars: {
      "--color-accent": "#c084fc",
      "--color-accent-hover": "#d8b4fe",
      "--color-accent-muted": "#c084fc26",
      "--color-bg-deep": "#08060e",
      "--color-bg-primary": "#100c18",
      "--color-bg-surface": "#1a1426",
      "--color-bg-elevated": "#241c34",
      "--color-bg-hover": "#2e2440",
      "--color-border-subtle": "#261e38",
      "--color-border-default": "#342a48",
      "--color-border-strong": "#4a3d62",
    },
  },
  {
    id: "rey",
    name: "Rey",
    subtitle: "The belonging you seek is ahead",
    swatch: "#fbbf24",
    vars: {
      "--color-accent": "#fbbf24",
      "--color-accent-hover": "#fcd34d",
      "--color-accent-muted": "#fbbf2426",
      "--color-bg-deep": "#0a0804",
      "--color-bg-primary": "#12100a",
      "--color-bg-surface": "#1c1912",
      "--color-bg-elevated": "#28241a",
      "--color-bg-hover": "#343020",
      "--color-border-subtle": "#28221a",
      "--color-border-default": "#383226",
      "--color-border-strong": "#504836",
    },
  },
  {
    id: "vader",
    name: "Darth Vader",
    subtitle: "I find your lack of faith disturbing",
    swatch: "#78838f",
    vars: {
      "--color-accent": "#8896a4",
      "--color-accent-hover": "#a8b4c0",
      "--color-accent-muted": "#8896a420",
      "--color-bg-deep": "#020202",
      "--color-bg-primary": "#060606",
      "--color-bg-surface": "#0c0c0e",
      "--color-bg-elevated": "#141416",
      "--color-bg-hover": "#1c1c20",
      "--color-border-subtle": "#141418",
      "--color-border-default": "#1e1e24",
      "--color-border-strong": "#2e2e36",
      "--color-error": "#ff4444",
    },
  },
  {
    id: "maul",
    name: "Darth Maul",
    subtitle: "At last we will reveal ourselves",
    swatch: "#ef4444",
    vars: {
      "--color-accent": "#ef4444",
      "--color-accent-hover": "#f87171",
      "--color-accent-muted": "#ef444426",
      "--color-bg-deep": "#0a0404",
      "--color-bg-primary": "#120808",
      "--color-bg-surface": "#1c1010",
      "--color-bg-elevated": "#2a1818",
      "--color-bg-hover": "#342020",
      "--color-border-subtle": "#2a181a",
      "--color-border-default": "#3a2226",
      "--color-border-strong": "#54323a",
    },
  },
  {
    id: "palpatine",
    name: "Palpatine",
    subtitle: "Unlimited power",
    swatch: "#a5b4fc",
    vars: {
      "--color-accent": "#a5b4fc",
      "--color-accent-hover": "#c7d2fe",
      "--color-accent-muted": "#a5b4fc22",
      "--color-bg-deep": "#04040c",
      "--color-bg-primary": "#0a0a16",
      "--color-bg-surface": "#121220",
      "--color-bg-elevated": "#1a1a2c",
      "--color-bg-hover": "#222238",
      "--color-border-subtle": "#1c1c30",
      "--color-border-default": "#282842",
      "--color-border-strong": "#3a3a5a",
    },
  },
];

export const defaultTheme = themes[0]!; // Obi-Wan

export function getThemeById(id: string): Theme | undefined {
  return themes.find((t) => t.id === id);
}

/** Apply a theme's CSS variables to the document root. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  for (const [prop, value] of Object.entries(theme.vars)) {
    root.style.setProperty(prop, value);
  }
}

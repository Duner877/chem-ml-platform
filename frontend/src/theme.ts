/** Theme tokens: the single source of truth for every colour in the GUI.
 *
 * Two themes ship with the platform:
 *
 * 1. ``wb-light``  -- the WorkBuddy white theme (light surfaces, dark text);
 * 2. ``wb-dark``   -- the WorkBuddy black theme (near-black surfaces).
 *
 * The first launch starts in ``wb-dark``; the user's choice is persisted in
 * ``localStorage`` and restored on every subsequent start.
 *
 * The tokens are *injected* as CSS custom properties (``--c-*``) at runtime and
 * ``tailwind.config.js`` maps its semantic colours onto those variables, so a
 * theme switch is a single ``setProperty`` sweep -- no re-render, no flash.
 * Values are stored as ``R G B`` channel triplets so Tailwind's ``/opacity``
 * modifiers (``bg-good/15``) keep working.
 */

export type ThemeId = "wb-light" | "wb-dark";

export interface ThemeTokens {
  /** App background (canvas). */
  canvas: string;
  /** Panel surface (top bar, side panels). */
  panel: string;
  /** Elevated surface (cards, node headers, inputs). */
  panel2: string;
  /** Hairline borders. */
  line: string;
  /** Primary text. */
  text: string;
  /** Secondary text. */
  textDim: string;
  /** Tertiary / placeholder text. */
  textFaint: string;
  /** Brand accent (buttons, focus, selection). */
  accent: string;
  /** Text colour drawn *on* an accent surface. */
  onAccent: string;
  good: string;
  warn: string;
  bad: string;
  /** Node body fill. */
  nodeBody: string;
  /** Node header fill. */
  nodeHeader: string;
  /** Widget (input) fill inside nodes. */
  widget: string;
  /** Node border. */
  nodeBorder: string;
  /** Connector stroke. */
  edge: string;
  /** Canvas grid dots. */
  grid: string;
  /** Minimap background. */
  minimap: string;
  /** Port / edge colour per scientific data type. */
  port: Record<string, string>;
}

/** WorkBuddy white theme. */
const WB_LIGHT: ThemeTokens = {
  canvas: "244 245 247", // #f4f5f7
  panel: "255 255 255",
  panel2: "236 238 242", // #eceef2
  line: "216 220 227", // #d8dce3
  text: "31 36 48", // #1f2430
  textDim: "90 98 114", // #5a6272
  textFaint: "139 147 163", // #8b93a3
  accent: "46 107 230", // #2e6be6
  onAccent: "255 255 255",
  good: "22 163 74", // #16a34a
  warn: "217 119 6", // #d97706
  bad: "220 38 38", // #dc2626
  nodeBody: "255 255 255",
  nodeHeader: "240 242 245", // #f0f2f5
  widget: "255 255 255",
  nodeBorder: "216 220 227",
  edge: "148 163 184", // #94a3b8
  grid: "226 230 236",
  minimap: "236 238 242",
  port: {
    MODEL: "185 28 28",
    CONDITIONING: "194 120 47",
    VAE: "126 58 158",
    LATENT: "190 70 140",
    IMAGE: "14 116 144",
    CLIP: "22 101 52",
    NOISE: "100 116 139",
    SAMPLER: "14 116 144",
    SIGMAS: "161 98 7",
    Spectrum: "29 78 216",
    Molecule: "22 101 52",
    Material: "161 98 7",
    Table: "126 58 158",
    Text: "71 85 105",
    Number: "194 65 12",
    Any: "100 116 139",
    ScientificObject: "100 116 139",
    SpectralMatch: "190 70 140",
    Reaction: "194 65 12",
    ScientificReport: "126 58 158",
    Boolean: "185 28 28",
    File: "100 116 139",
  },
};

/** WorkBuddy black theme. */
const WB_DARK: ThemeTokens = {
  canvas: "11 13 18", // #0b0d12
  panel: "18 21 29", // #12151d
  panel2: "26 30 40", // #1a1e28
  line: "38 43 54", // #262b36
  text: "230 233 239", // #e6e9ef
  textDim: "154 163 178", // #9aa3b2
  textFaint: "107 114 128", // #6b7280
  accent: "79 141 255", // #4f8dff
  onAccent: "255 255 255",
  good: "52 211 153", // #34d399
  warn: "251 191 36", // #fbbf24
  bad: "248 113 113", // #f87171
  nodeBody: "26 30 40",
  nodeHeader: "21 25 35", // #151923
  widget: "15 18 24", // #0f1218
  nodeBorder: "38 43 54",
  edge: "75 85 104", // #4b5568
  grid: "30 35 46",
  minimap: "15 18 24",
  port: {
    MODEL: "220 90 90",
    CONDITIONING: "216 154 80",
    VAE: "176 128 224",
    LATENT: "224 130 190",
    IMAGE: "70 180 200",
    CLIP: "140 200 130",
    NOISE: "110 118 130",
    SAMPLER: "70 180 200",
    SIGMAS: "220 190 110",
    Spectrum: "100 170 240",
    Molecule: "140 200 130",
    Material: "220 190 110",
    Table: "176 128 224",
    Text: "170 178 190",
    Number: "216 154 80",
    Any: "150 158 175",
    ScientificObject: "150 158 175",
    SpectralMatch: "224 130 190",
    Reaction: "216 154 80",
    ScientificReport: "176 128 224",
    Boolean: "220 90 90",
    File: "110 118 130",
  },
};

export const THEMES: Record<ThemeId, ThemeTokens> = {
  "wb-light": WB_LIGHT,
  "wb-dark": WB_DARK,
};

export const THEME_IDS: ThemeId[] = ["wb-dark", "wb-light"];

/** Theme used on the very first launch (before the user picks one). */
export const DEFAULT_THEME: ThemeId = "wb-dark";

/** localStorage key remembering the chosen theme across sessions. */
const STORAGE_KEY = "chemml-theme";

/** CSS custom property prefix -- kept in sync with ``tailwind.config.js``. */
const CSS_PREFIX = "--c-";

function channel(value: string): string {
  return value.trim();
}

/** Write every token of ``themeId`` onto ``<html>`` as ``--c-*`` channels. */
export function applyTheme(themeId: ThemeId): void {
  if (typeof document === "undefined") return;
  const tokens = THEMES[themeId] ?? THEMES[DEFAULT_THEME];
  const root = document.documentElement;
  const simple: Array<[string, string]> = [
    ["canvas", tokens.canvas],
    ["panel", tokens.panel],
    ["panel2", tokens.panel2],
    ["line", tokens.line],
    ["text", tokens.text],
    ["text-dim", tokens.textDim],
    ["text-faint", tokens.textFaint],
    ["accent", tokens.accent],
    ["on-accent", tokens.onAccent],
    ["good", tokens.good],
    ["warn", tokens.warn],
    ["bad", tokens.bad],
    ["node-body", tokens.nodeBody],
    ["node-header", tokens.nodeHeader],
    ["widget", tokens.widget],
    ["node-border", tokens.nodeBorder],
    ["edge", tokens.edge],
    ["grid", tokens.grid],
    ["minimap", tokens.minimap],
  ];
  for (const [name, value] of simple) {
    root.style.setProperty(`${CSS_PREFIX}${name}`, channel(value));
  }
  root.setAttribute("data-theme", themeId);
  try {
    localStorage.setItem(STORAGE_KEY, themeId);
  } catch {
    /* private mode -- the theme simply is not remembered */
  }
}

/**
 * Theme id persisted by a previous session.  First launch (no stored choice)
 * starts in the WorkBuddy black theme; later launches restore the user's pick.
 */
export function storedTheme(): ThemeId {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && (THEME_IDS as string[]).includes(value)) {
      return value as ThemeId;
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

/** Theme to start with: ``?theme=<id>`` (deep link) beats the stored choice. */
export function initialTheme(): ThemeId {
  if (typeof window !== "undefined") {
    const requested = new URLSearchParams(window.location.search).get("theme");
    if (requested && (THEME_IDS as string[]).includes(requested)) {
      return requested as ThemeId;
    }
  }
  return storedTheme();
}

/** Port / edge colour for a scientific data type (stable fallback: Any). */
export function portColor(tokens: ThemeTokens, dataType: string): string {
  return tokens.port[dataType] ?? tokens.port.Any ?? "139 147 167";
}

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
 * v0.7.2 -- **monochrome design language**.  The accent used to be a saturated
 * blue (``#2e6be6`` / ``#4f8dff``), which made every button, focus ring, tab
 * underline, selected connector and plotted trace shout in the same hue and
 * read as a foreign element next to the WorkBuddy shell.  Both themes are now
 * strictly achromatic: ``accent`` is near-black on light and near-white on
 * dark, connectors are neutral grey, and the port palette is a *greyscale ramp*
 * (identity is carried by lightness + the printed ``data_type`` label, not by
 * hue).  ``good`` / ``warn`` / ``bad`` stay chromatic on purpose -- they encode
 * run state, not branding.
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
  /** Brand accent (buttons, focus, selection) -- achromatic by design. */
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

/**
 * Greyscale port ramp.
 *
 * The port palette used to be a rainbow keyed by data type.  Under the
 * monochrome language the same information is carried by *lightness* only:
 * seven neutral steps from near-black to near-white on the light theme, and
 * the mirrored ramp on the dark theme.  Because achromatic steps are harder to
 * tell apart than hues, every place that draws a port also prints the
 * ``data_type`` name next to it (node card, inspector, palette).
 */
const GREY_LIGHT = [
  "24 28 35", // 0 near-black
  "52 59 70",
  "82 90 102",
  "112 121 134", // 3 mid
  "142 151 164",
  "170 178 189",
  "198 205 214", // 6 near-white
] as const;

const GREY_DARK = [
  "240 242 246", // 0 near-white
  "210 215 222",
  "180 186 196",
  "150 157 168", // 3 mid
  "120 128 140",
  "92 99 111",
  "64 70 81", // 6 near-black
] as const;

/** WorkBuddy white theme. */
const WB_LIGHT: ThemeTokens = {
  canvas: "244 245 247", // #f4f5f7
  panel: "255 255 255",
  panel2: "236 238 242", // #eceef2
  line: "216 220 227", // #d8dce3
  text: "31 36 48", // #1f2430
  textDim: "90 98 114", // #5a6272
  textFaint: "139 147 163", // #8b93a3
  accent: "26 30 40", // #1a1e28 -- near-black, not blue
  onAccent: "255 255 255",
  good: "22 163 74", // #16a34a -- run state only
  warn: "217 119 6", // #d97706
  bad: "220 38 38", // #dc2626
  nodeBody: "255 255 255",
  nodeHeader: "240 242 245", // #f0f2f5
  widget: "255 255 255",
  nodeBorder: "216 220 227",
  edge: "138 145 158",
  grid: "226 230 236",
  minimap: "236 238 242",
  port: {
    MODEL: GREY_LIGHT[0],
    CONDITIONING: GREY_LIGHT[4],
    VAE: GREY_LIGHT[2],
    LATENT: GREY_LIGHT[5],
    IMAGE: GREY_LIGHT[3],
    CLIP: GREY_LIGHT[1],
    NOISE: GREY_LIGHT[5],
    SAMPLER: GREY_LIGHT[3],
    SIGMAS: GREY_LIGHT[4],
    Spectrum: GREY_LIGHT[0],
    Molecule: GREY_LIGHT[1],
    Material: GREY_LIGHT[4],
    Table: GREY_LIGHT[2],
    Text: GREY_LIGHT[5],
    Number: GREY_LIGHT[6],
    Any: GREY_LIGHT[3],
    ScientificObject: GREY_LIGHT[3],
    SpectralMatch: GREY_LIGHT[5],
    Reaction: GREY_LIGHT[6],
    ScientificReport: GREY_LIGHT[2],
    Boolean: GREY_LIGHT[0],
    File: GREY_LIGHT[4],
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
  accent: "236 239 244", // #eceff4 -- near-white, not blue
  onAccent: "16 18 22",
  good: "52 211 153", // #34d399 -- run state only
  warn: "251 191 36", // #fbbf24
  bad: "248 113 113", // #f87171
  nodeBody: "26 30 40",
  nodeHeader: "21 25 35", // #151923
  widget: "15 18 24", // #0f1218
  nodeBorder: "38 43 54",
  edge: "86 93 106",
  grid: "30 35 46",
  minimap: "15 18 24",
  port: {
    MODEL: GREY_DARK[0],
    CONDITIONING: GREY_DARK[4],
    VAE: GREY_DARK[2],
    LATENT: GREY_DARK[5],
    IMAGE: GREY_DARK[3],
    CLIP: GREY_DARK[1],
    NOISE: GREY_DARK[5],
    SAMPLER: GREY_DARK[3],
    SIGMAS: GREY_DARK[4],
    Spectrum: GREY_DARK[0],
    Molecule: GREY_DARK[1],
    Material: GREY_DARK[4],
    Table: GREY_DARK[2],
    Text: GREY_DARK[5],
    Number: GREY_DARK[6],
    Any: GREY_DARK[3],
    ScientificObject: GREY_DARK[3],
    SpectralMatch: GREY_DARK[5],
    Reaction: GREY_DARK[6],
    ScientificReport: GREY_DARK[2],
    Boolean: GREY_DARK[0],
    File: GREY_DARK[4],
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

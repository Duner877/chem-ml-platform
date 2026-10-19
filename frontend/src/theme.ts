/** Theme tokens: the single source of truth for every colour in the GUI.
 *
 * Two token sets ship with the platform:
 *
 * 1. ``wb-light``  -- the white theme (light surfaces, dark text);
 * 2. ``wb-dark``   -- the black theme (near-black surfaces).
 *
 * A third *menu entry*, ``wb-system``, follows the OS appearance.  It is a
 * setting rather than a token set: `resolveTheme()` maps it onto one of the two
 * above at apply time, and it keeps following afterwards through
 * `onSystemThemeChange`.  See {@link ThemeSetting} for why it must not become
 * a third entry in `THEMES`.
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

/**
 * What the user picks: a concrete theme, or "follow the system".
 *
 * `wb-system` is deliberately **not** a member of {@link ThemeId}.  It is a
 * mode, not a third set of tokens -- it resolves to `wb-dark` or `wb-light` at
 * apply time.  Modelling it as a peer in the token table would fail silently:
 * `THEMES["wb-system"]` is `undefined`, so the five indexing sites fall back
 * to `DEFAULT_THEME` and paint black on a light system while the menu still
 * says "follow the system".  Resolution goes through {@link resolveTheme},
 * which cannot express that state.
 */
export type ThemeSetting = ThemeId | "wb-system";

/** Every selectable entry, in menu order. */
export const THEME_SETTINGS: ThemeSetting[] = ["wb-dark", "wb-light", "wb-system"];

/** The two entries that actually carry tokens. */
export const THEME_IDS: ThemeId[] = ["wb-dark", "wb-light"];

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

/** Theme used on the very first launch (before the user picks one). */
export const DEFAULT_THEME: ThemeId = "wb-dark";

/** localStorage key remembering the chosen theme across sessions. */
const STORAGE_KEY = "chemml-theme";

/** CSS custom property prefix -- kept in sync with ``tailwind.config.js``. */
const CSS_PREFIX = "--c-";

/**
 * The desktop bridge, when the GUI runs inside Electron.
 *
 * Declared structurally rather than imported so this module stays free of any
 * dependency on the shell: in a browser it is simply absent.
 */
interface DesktopThemeBridge {
  systemTheme?: () => Promise<{ dark: boolean; source?: string } | null>;
  onSystemThemeChange?: (cb: (data: { dark: boolean }) => void) => void;
}

function desktopBridge(): DesktopThemeBridge | null {
  if (typeof window === "undefined") return null;
  const host = window as unknown as { chemmlDesktop?: DesktopThemeBridge };
  return host.chemmlDesktop ?? null;
}

/** Last known answer from the Electron shell, per bridge instance. */
const systemThemeCache = new WeakMap<object, boolean>();

/**
 * True when the OS asks for a dark UI.
 *
 * `matchMedia` is the primary signal and works in both the browser and
 * Electron's renderer.  In Electron the *shell's* answer wins, because
 * `nativeTheme.shouldUseDarkColors` is what paints native chrome -- when the two
 * disagree the app looks half-themed, and the shell is what the eye reads first.
 *
 * A missing capability (SSR, an old webview, a bridge that has not answered
 * yet) resolves to the dark default, which is also the first-launch theme, so
 * the fallback path is the same one we would have chosen anyway rather than a
 * different-looking surprise.
 */
export function systemPrefersDark(): boolean {
  const bridge = desktopBridge();
  if (bridge?.systemTheme) {
    // Synchronous by necessity: theme resolution happens inside React render
    // and inside a zustand selector, where a promise cannot be awaited.  The
    // bridge caches the shell's answer after the first read, so this is a
    // plain lookup after startup; a slow first call simply renders the default
    // once and `onSystemThemeChange` corrects it.
    const cached = systemThemeCache.get(bridge);
    if (cached !== undefined) return cached;
    void bridge
      .systemTheme()
      .then((answer) => {
        if (answer && typeof answer.dark === "boolean") {
          systemThemeCache.set(bridge, answer.dark);
        }
      })
      .catch(() => undefined);
  }
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return DEFAULT_THEME === "wb-dark";
  }
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return DEFAULT_THEME === "wb-dark";
  }
}

/**
 * Turn a user *setting* into the concrete theme whose tokens get painted.
 *
 * Every consumer of tokens must go through this.  Indexing ``THEMES`` with a
 * setting directly is the bug described on {@link ThemeSetting}.
 */
export function resolveTheme(setting: ThemeSetting): ThemeId {
  if (setting === "wb-system") {
    return systemPrefersDark() ? "wb-dark" : "wb-light";
  }
  return THEMES[setting] ? setting : DEFAULT_THEME;
}

/**
 * Subscribe to OS appearance changes; returns an unsubscribe function.
 *
 * Called by the store so a machine that switches to dark at sunset actually
 * repaints.  Without it "follow the system" would only be true at launch -- the
 * most common way this feature is judged broken.
 *
 * Both signals are wired.  `matchMedia` covers the browser and is the one that
 * works everywhere; in Electron the shell's `nativeTheme` also announces the
 * change, and updating the cache from it is what keeps the *next* synchronous
 * `systemPrefersDark()` read correct.  Duplicates are harmless -- the handler
 * repaints the same resolved theme either way.
 */
export function onSystemThemeChange(handler: () => void): () => void {
  const bridge = desktopBridge();
  if (bridge?.onSystemThemeChange) {
    bridge.onSystemThemeChange((data) => {
      if (bridge && typeof data?.dark === "boolean") {
        systemThemeCache.set(bridge, data.dark);
      }
      handler();
    });
  }
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }
  let query: MediaQueryList;
  try {
    query = window.matchMedia("(prefers-color-scheme: dark)");
  } catch {
    return () => undefined;
  }
  const listener = () => handler();
  // Safari < 14 and older WebKit only have the deprecated form.
  if (typeof query.addEventListener === "function") {
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }
  query.addListener(listener);
  return () => query.removeListener(listener);
}

function channel(value: string): string {
  return value.trim();
}

/**
 * Paint the tokens for ``setting`` onto `<html>` and remember the choice.
 *
 * The *setting* is persisted, not the resolved theme: storing the resolved id
 * would turn "follow the system" into a frozen snapshot on the next launch,
 * which is the one behaviour it must never have.
 */
export function applyTheme(setting: ThemeSetting): void {
  const themeId = resolveTheme(setting);
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
  // data-theme carries the *resolved* id so CSS and the Electron shell can
  // read what is actually on screen; data-theme-setting carries the choice so
  // "is this following the system" stays answerable.
  root.setAttribute("data-theme", themeId);
  root.setAttribute("data-theme-setting", setting);
  try {
    localStorage.setItem(STORAGE_KEY, setting);
  } catch {
    /* private mode -- the theme simply is not remembered */
  }
}

/**
 * Theme setting persisted by a previous session.  First launch (no stored
 * choice) starts in the WorkBuddy black theme; later launches restore the pick.
 */
export function storedTheme(): ThemeSetting {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && (THEME_SETTINGS as string[]).includes(value)) {
      return value as ThemeSetting;
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

/** Setting to start with: ``?theme=<id>`` (deep link) beats the stored choice. */
export function initialTheme(): ThemeSetting {
  if (typeof window !== "undefined") {
    const requested = new URLSearchParams(window.location.search).get("theme");
    if (requested && (THEME_SETTINGS as string[]).includes(requested)) {
      return requested as ThemeSetting;
    }
  }
  return storedTheme();
}

/** Port / edge colour for a scientific data type (stable fallback: Any). */
export function portColor(tokens: ThemeTokens, dataType: string): string {
  return tokens.port[dataType] ?? tokens.port.Any ?? "139 147 167";
}

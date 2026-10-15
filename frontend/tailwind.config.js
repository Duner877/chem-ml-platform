/** @type {import('tailwindcss').Config} */

/**
 * Every semantic colour is a CSS custom property (``--c-*``) written by
 * ``src/theme.ts`` at runtime, so switching between the ComfyUI / WorkBuddy
 * white / WorkBuddy black themes is a variable sweep rather than a rebuild.
 * Values are ``R G B`` channel triplets, which keeps Tailwind's ``/opacity``
 * modifiers (``bg-good/15``, ``text-accent/80``) working.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--c-canvas) / <alpha-value>)",
        panel: "rgb(var(--c-panel) / <alpha-value>)",
        panel2: "rgb(var(--c-panel2) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        accent: "rgb(var(--c-accent) / <alpha-value>)",
        onAccent: "rgb(var(--c-on-accent) / <alpha-value>)",
        good: "rgb(var(--c-good) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        bad: "rgb(var(--c-bad) / <alpha-value>)",
        nodeBody: "rgb(var(--c-node-body) / <alpha-value>)",
        nodeHeader: "rgb(var(--c-node-header) / <alpha-value>)",
        widget: "rgb(var(--c-widget) / <alpha-value>)",
        nodeBorder: "rgb(var(--c-node-border) / <alpha-value>)",
        edge: "rgb(var(--c-edge) / <alpha-value>)",
        grid: "rgb(var(--c-grid) / <alpha-value>)",
        // The legacy ``slate`` scale is remapped onto the theme text levels so
        // every existing utility (text-slate-100 … text-slate-600) follows the
        // active theme instead of pinning a dark-only palette.
        slate: {
          100: "rgb(var(--c-text) / <alpha-value>)",
          200: "rgb(var(--c-text) / <alpha-value>)",
          300: "rgb(var(--c-text-dim) / <alpha-value>)",
          400: "rgb(var(--c-text-dim) / <alpha-value>)",
          500: "rgb(var(--c-text-dim) / <alpha-value>)",
          600: "rgb(var(--c-text-faint) / <alpha-value>)",
          700: "rgb(var(--c-text-faint) / <alpha-value>)",
          800: "rgb(var(--c-panel2) / <alpha-value>)",
          900: "rgb(var(--c-panel) / <alpha-value>)",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

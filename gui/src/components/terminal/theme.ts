import type { ITheme } from "@xterm/xterm";

export const glassTheme: ITheme = {
  background: "rgba(15, 17, 28, 0.65)",
  foreground: "#e6e6fa",
  cursor: "#e6e6fa",
  cursorAccent: "#0a0c19",
  selectionBackground: "rgba(165, 180, 252, 0.25)",
  black: "#1a1b26",
  red: "#fda4af",
  green: "#86efac",
  yellow: "#fde68a",
  blue: "#a5b4fc",
  magenta: "#c4b5fd",
  cyan: "#67e8f9",
  white: "#e6e6fa",
  brightBlack: "#6b7280",
  brightRed: "#fb7185",
  brightGreen: "#4ade80",
  brightYellow: "#facc15",
  brightBlue: "#818cf8",
  brightMagenta: "#a78bfa",
  brightCyan: "#22d3ee",
  brightWhite: "#ffffff",
};

export const terminalFont = {
  family: "'Commit Mono', ui-monospace, 'JetBrains Mono', monospace",
  size: 13.5,
  lineHeight: 1.5,
  weight: 400 as const,
};

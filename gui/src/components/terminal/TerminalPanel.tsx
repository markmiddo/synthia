import { NativeTerminalView } from "./NativeTerminalView";

interface TerminalPanelProps {
  visible: boolean;
}

/// Wezterm-style tab strip — purely visual for v1 (single persistent
/// session).  Sets up the chrome that makes the panel read as a real
/// terminal application rather than a black overlay.
function TabStrip() {
  return (
    <div
      className="native-term-tabstrip"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 10px",
        background: "rgba(255,255,255,0.02)",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
        flexShrink: 0,
        userSelect: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 12px",
          background: "rgba(99,102,241,0.10)",
          border: "1px solid rgba(99,102,241,0.20)",
          borderRadius: 6,
          fontSize: 11,
          color: "rgba(255,255,255,0.85)",
          fontFamily:
            "ui-monospace, 'Commit Mono', 'JetBrains Mono', Menlo, monospace",
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#22d3ee",
            boxShadow: "0 0 6px rgba(34,211,238,0.7)",
          }}
        />
        shell
      </div>
      <div style={{ flex: 1 }} />
      <div
        style={{
          fontSize: 10,
          color: "rgba(255,255,255,0.35)",
          fontFamily:
            "ui-monospace, 'Commit Mono', 'JetBrains Mono', Menlo, monospace",
        }}
      >
        native · wayland subsurface
      </div>
    </div>
  );
}

export function TerminalPanel({ visible }: TerminalPanelProps) {
  return (
    <div
      className="terminal-panel"
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
    >
      <TabStrip />
      <div style={{ flex: 1, minHeight: 0 }}>
        <NativeTerminalView visible={visible} />
      </div>
    </div>
  );
}

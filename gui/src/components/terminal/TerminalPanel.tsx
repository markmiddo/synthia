import { NativeTerminalView } from "./NativeTerminalView";

interface TerminalPanelProps {
  visible: boolean;
}

export function TerminalPanel({ visible }: TerminalPanelProps) {
  return (
    <div className="terminal-panel">
      <NativeTerminalView visible={visible} />
    </div>
  );
}

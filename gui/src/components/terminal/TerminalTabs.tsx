interface TabState {
  uiId: string;
  title: string;
}

interface TerminalTabsProps {
  tabs: TabState[];
  activeId: string | null;
  onSelect: (uiId: string) => void;
  onClose: (uiId: string) => void;
  onNewShell: () => void;
  onNewClaude: () => void;
}

export function TerminalTabs(props: TerminalTabsProps) {
  const { tabs, activeId, onSelect, onClose, onNewShell, onNewClaude } = props;

  function handleMouseDown(e: React.MouseEvent, uiId: string) {
    if (e.button === 1) {
      e.preventDefault();
      onClose(uiId);
    }
  }

  return (
    <div className="terminal-tabs" role="tablist">
      {tabs.map((tab) => (
        <div
          key={tab.uiId}
          role="tab"
          aria-selected={activeId === tab.uiId}
          className={`terminal-tab${activeId === tab.uiId ? " active" : ""}`}
          onClick={() => onSelect(tab.uiId)}
          onMouseDown={(e) => handleMouseDown(e, tab.uiId)}
          title={tab.title}
        >
          <span className="title">{tab.title}</span>
          <span
            className="close"
            onClick={(e) => {
              e.stopPropagation();
              onClose(tab.uiId);
            }}
          >
            ×
          </span>
        </div>
      ))}
      <div className="new-tab" onClick={onNewShell} title="New shell (Ctrl+Shift+T)">
        +
      </div>
      <div
        className="new-tab claude"
        onClick={onNewClaude}
        title="New Claude session (Ctrl+Shift+C)"
      >
        + Claude
      </div>
    </div>
  );
}

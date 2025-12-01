import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./Overlay.css";

function Overlay() {
  const [isActive, setIsActive] = useState(false);

  useEffect(() => {
    // Listen for recording state changes from Tauri backend
    const unlistenRecording = listen<boolean>("recording", (event) => {
      setIsActive(event.payload);
    });

    return () => {
      unlistenRecording.then((fn) => fn());
    };
  }, []);

  // Handle drag - must use startDragging for transparent windows
  async function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const appWindow = getCurrentWindow();
    await appWindow.startDragging();
  }

  // Generate bars
  const bars = Array.from({ length: 5 }, (_, i) => {
    const height = 6 + i * 2;
    return (
      <div
        key={i}
        className="bar"
        style={{ height: `${height}px` }}
      />
    );
  });

  return (
    <div
      className={`overlay-container ${isActive ? "active" : ""}`}
      onMouseDown={startDrag}
    >
      <div className="pill">
        <div className="indicator" />
        <div className="bars">{bars}</div>
      </div>
    </div>
  );
}

export default Overlay;

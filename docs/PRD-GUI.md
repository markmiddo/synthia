# Synthia GUI - Product Requirements Document

**Version:** 0.4
**Status:** Draft
**Author:** Mark Middo
**Last Updated:** December 2024

---

## Overview

### Problem Statement

Synthia currently runs as a headless background process with no visual feedback. Users can't easily:
- See if Synthia is running or what state it's in
- Start/stop the service without terminal commands
- Change settings without editing config files
- View transcription history or debug issues

This creates friction, especially for users less comfortable with the terminal.

### Solution

Build a lightweight native GUI that provides visual feedback, easy controls, and settings management while maintaining Synthia's core value: privacy-first, local-first voice assistant.

### Success Metrics

- **Adoption:** 80% of users prefer GUI over CLI within 30 days of release
- **Reliability:** GUI adds <50MB RAM overhead, <1% CPU idle
- **Usability:** New users can configure and use Synthia without documentation
- **Performance:** GUI response time <100ms for all interactions

---

## User Personas

### Primary: Developer Dave
- Uses Synthia for hands-free coding with Claude Code
- Wants quick visual confirmation that voice input is being captured
- Needs easy mode switching (Quick/Dev/Remote)
- Values minimal UI that doesn't interrupt workflow

### Secondary: Power User Paula
- Uses Synthia for desktop automation and assistant tasks
- Wants to customize hotkeys, voices, and models
- Appreciates detailed settings and history
- May run multiple configurations

### Tertiary: New User Nick
- Just discovered Synthia, evaluating if it works for them
- Needs clear visual feedback to understand what's happening
- Wants simple setup wizard
- May not be comfortable with config files

---

## Features

### 1. Floating Bar (Core UI)

**Priority:** P0 - Must Have

The primary interface - a minimal, floating bar that appears during voice interaction.

#### States

| State | Visual | Behavior |
|-------|--------|----------|
| **Hidden** | Not visible | Default state when not recording |
| **Listening** | Pulsing cyan border, waveform | Appears when hotkey pressed |
| **Processing** | Spinning indicator, "Thinking..." | After release, during transcription/LLM |
| **Speaking** | Speaker icon, audio waveform | During TTS playback |
| **Error** | Red border, error icon | On failure, auto-dismiss after 3s |

#### Behavior

- **Appears:** On hotkey press (Right Ctrl or Right Alt)
- **Position:** Centered top of screen, 80px from top edge
- **Size:** 400px wide × 60px tall (expanded: 400px × 200px)
- **Always on top:** Yes, but not focusable (doesn't steal keyboard)
- **Draggable:** Yes, remembers position
- **Animation:** Fade in 150ms, fade out 300ms

#### Components

```
┌─────────────────────────────────────────────────────┐
│  [Mode Icon]  ████████░░░░░░░░  [State Text]  [╳]  │
│               ^ waveform ^                          │
└─────────────────────────────────────────────────────┘
```

- **Mode Icon:** Quick (bolt), Dev (code), Remote (phone)
- **Waveform:** Real-time audio level visualization
- **State Text:** "Listening...", "Processing...", "Speaking..."
- **Close Button:** Cancel current operation

#### Expanded View (on hover or click)

```
┌─────────────────────────────────────────────────────┐
│  [Mode Icon]  ████████░░░░░░░░  [State Text]  [╳]  │
├─────────────────────────────────────────────────────┤
│  "Your transcribed text appears here in real-time" │
│                                                     │
│  [Copy]  [Retry]  [Send to Claude]                 │
└─────────────────────────────────────────────────────┘
```

---

### 2. System Tray

**Priority:** P0 - Must Have

Persistent access point when floating bar is hidden.

#### Tray Icon States

| State | Icon | Tooltip |
|-------|------|---------|
| Ready | Cyan circle | "Synthia - Ready (Quick Mode)" |
| Listening | Pulsing cyan | "Synthia - Listening..." |
| Processing | Yellow circle | "Synthia - Processing..." |
| Disabled | Gray circle | "Synthia - Paused" |
| Error | Red circle | "Synthia - Error: [message]" |

#### Right-Click Menu

```
┌──────────────────────────┐
│ ● Quick Mode        ✓   │
│ ○ Dev Mode              │
│ ○ Remote Mode           │
├──────────────────────────┤
│ ⏸ Pause Synthia         │
│ 🔄 Restart               │
├──────────────────────────┤
│ 📜 Voice History         │
│ ⚙️ Settings              │
├──────────────────────────┤
│ 📖 Documentation         │
│ 🐛 Report Issue          │
├──────────────────────────┤
│ ❌ Quit                   │
└──────────────────────────┘
```

#### Left-Click Behavior

- Single click: Toggle pause/resume
- Double click: Open settings

---

### 3. Settings Panel

**Priority:** P0 - Must Have

Comprehensive settings accessible from tray menu.

#### Tabs

**General**
- Start on login (checkbox)
- Show floating bar (checkbox)
- Show notifications (checkbox)
- Theme: Dark / Light / System

**Hotkeys**
- Dictation key: [Key capture button] (default: Right Ctrl)
- Assistant key: [Key capture button] (default: Right Alt)
- Toggle pause: [Key capture button] (default: none)
- Push-to-talk vs toggle mode (radio)

**Audio**
- Input device: [Dropdown]
- Test microphone: [Button with level meter]
- Play sounds on record start/stop (checkbox)

**Speech Recognition**
- Engine: Local Whisper / Google Cloud (radio)
- Whisper model: tiny / base / small / medium / large (dropdown)
- Language: [Dropdown]
- Show confidence scores (checkbox)

**Text-to-Speech**
- Engine: Local Piper / Google Cloud (radio)
- Voice: [Dropdown with preview button]
- Speed: [Slider 0.5x - 2.0x]
- Test voice: [Button]

**Assistant (Quick Mode)**
- Engine: Local Ollama / Claude API (radio)
- Local model: [Dropdown]
- Personality prompt: [Text area]
- Conversation memory: [Slider 0-20]

**Dev Mode**
- Claude Code integration (checkbox)
- Speak responses (checkbox)
- Plan approval required (checkbox)

**Remote Mode**
- Enable Telegram bot (checkbox)
- Bot token: [Password field]
- Allowed users: [List with add/remove]
- Test connection: [Button]

**Advanced**
- Log level: Error / Warn / Info / Debug
- Open log file: [Button]
- Reset to defaults: [Button]
- Export config: [Button]
- Import config: [Button]

---

### 4. Voice History Panel

**Priority:** P1 - Should Have

View and manage recent voice interactions.

#### Layout

```
┌─────────────────────────────────────────────────────────┐
│  Voice History                          [🔍] [Clear]    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐   │
│  │ 12:34 PM - Quick Mode                    [Copy] │   │
│  │ "Open Chrome and go to GitHub"                  │   │
│  │ ✓ Executed: Opened google-chrome               │   │
│  └─────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 12:32 PM - Dev Mode                      [Copy] │   │
│  │ "Add error handling to the login function"      │   │
│  │ → Sent to Claude Code                          │   │
│  └─────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 12:30 PM - Dictation                     [Copy] │   │
│  │ "Hello world this is a test of dictation"       │   │
│  │ ✓ Typed 42 characters                          │   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Showing 3 of 47 entries              [Load More]      │
└─────────────────────────────────────────────────────────┘
```

#### Features

- Search/filter by text or mode
- Copy individual entries
- Clear history
- Export to file
- Persistence across restarts (SQLite)
- Configurable retention (last 100 / 7 days / forever)

---

### 5. First-Run Setup Wizard

**Priority:** P1 - Should Have

Guided setup for new users.

#### Steps

1. **Welcome**
   - Brief intro to Synthia
   - Privacy notice (all local by default)

2. **Microphone Setup**
   - Select input device
   - Test recording with visual feedback
   - Troubleshooting tips if no audio

3. **Hotkey Configuration**
   - Set dictation hotkey (with conflict detection)
   - Set assistant hotkey
   - Quick tutorial on hold-to-talk

4. **Voice Selection**
   - Preview available Piper voices
   - Select preferred voice
   - Download if needed

5. **Mode Selection**
   - Explain Quick vs Dev vs Remote
   - Enable/disable each mode
   - Claude Code integration prompt (if Dev mode)

6. **Ready!**
   - Summary of configuration
   - "Try it now" prompt
   - Link to documentation

---

### 6. Notifications

**Priority:** P2 - Nice to Have

System notifications for key events.

| Event | Notification |
|-------|--------------|
| Startup | "Synthia is ready" |
| Mode change | "Switched to Dev Mode" |
| Error | "Microphone error: [details]" |
| Remote command | "Remote: [command preview]" |
| Update available | "Synthia v0.5 is available" |

---

## Technical Architecture

### Tech Stack Options

#### Option A: Tauri (Recommended)

**Pros:**
- Rust backend (fast, safe, small binary)
- Web frontend (familiar tech: HTML/CSS/JS or React)
- Cross-platform (Linux, macOS, Windows)
- ~5MB bundle size
- Native system tray support
- IPC between Rust and frontend

**Cons:**
- Two languages (Rust + JS)
- WebView dependency

**Structure:**
```
synthia-gui/
├── src-tauri/          # Rust backend
│   ├── src/
│   │   ├── main.rs
│   │   ├── tray.rs
│   │   └── ipc.rs
│   └── Cargo.toml
├── src/                # Web frontend
│   ├── components/
│   ├── App.tsx
│   └── main.tsx
├── package.json
└── tauri.conf.json
```

#### Option B: Pure Rust (egui/iced)

**Pros:**
- Single language
- No web dependencies
- Immediate mode GUI (egui) or Elm-like (iced)
- Maximum performance

**Cons:**
- Steeper learning curve
- Less mature ecosystem
- Custom styling more difficult

#### Option C: Python + Qt

**Pros:**
- Same language as Synthia core
- Mature, battle-tested
- Rich widget library

**Cons:**
- Larger bundle size (~100MB+)
- Licensing considerations (GPL/LGPL)
- Less "native" feel

### Recommendation

**Tauri** is the recommended approach:
1. Cross-platform from day one
2. Small bundle size aligns with Synthia's lightweight philosophy
3. Web frontend allows rapid UI iteration
4. Rust backend ensures performance for audio visualization

### Communication with Synthia Core

The GUI will communicate with the existing Python Synthia core via:

1. **Unix Domain Socket** (Linux/macOS) / **Named Pipe** (Windows)
   - Low latency for real-time state updates
   - Bidirectional communication

2. **Protocol:**
```json
// GUI → Core
{"type": "command", "action": "start_recording", "mode": "quick"}
{"type": "command", "action": "stop_recording"}
{"type": "command", "action": "set_mode", "mode": "dev"}
{"type": "config", "key": "hotkey.dictation", "value": "ctrl_r"}

// Core → GUI
{"type": "state", "status": "listening", "mode": "quick"}
{"type": "state", "status": "processing", "progress": 0.5}
{"type": "audio", "level": 0.73}
{"type": "transcription", "text": "Hello world", "confidence": 0.95}
{"type": "error", "message": "Microphone not found"}
```

3. **Shared Config:**
   - GUI reads/writes `~/.config/synthia/config.yaml`
   - Core watches for changes and reloads

---

## Design Guidelines

### Visual Style

- **Theme:** Dark by default (matches terminal aesthetic)
- **Primary Color:** Cyan (#06b6d4) - consistent with website
- **Accent:** Blue (#2563eb) for gradients
- **Background:** Near-black (#0a0a0f)
- **Text:** White (#ffffff) and slate (#94a3b8)
- **Borders:** Subtle slate (#1e293b)

### Typography

- **Headings:** Inter or system sans-serif, bold
- **Body:** Inter or system sans-serif, regular
- **Monospace:** JetBrains Mono (for transcriptions)

### Iconography

- Use Lucide icons (consistent with website)
- 20px standard size
- Stroke width 1.5px

### Motion

- **Transitions:** 150ms ease-out
- **Waveform:** 60fps, smooth interpolation
- **Pulse animation:** 1s ease-in-out infinite

### Accessibility

- Keyboard navigable (Tab, Enter, Escape)
- Screen reader labels on all controls
- Minimum contrast ratio 4.5:1
- Focus indicators visible
- Reduced motion option

---

## Milestones (AI-Assisted Development)

**Target: Linux MVP in 1 week**

### Day 1: Foundation
- [ ] Tauri project setup with React frontend
- [ ] System tray with basic menu (start/stop/quit)
- [ ] IPC socket connection to Synthia core
- [ ] Core sends state updates to GUI

### Day 2: Floating Bar
- [ ] Floating bar component (appears on hotkey)
- [ ] State visualization (listening/processing/speaking)
- [ ] Real-time audio level meter
- [ ] Auto-hide on completion

### Day 3: Settings Panel
- [ ] Settings window with tabs
- [ ] Hotkey configuration
- [ ] Audio device selection
- [ ] Voice/model selection dropdowns
- [ ] Config file read/write

### Day 4: Voice History & Polish
- [ ] Voice history panel with SQLite
- [ ] Copy/search/clear functionality
- [ ] Mode switching from tray
- [ ] Notifications

### Day 5: Integration & Testing
- [ ] Full integration with Synthia core
- [ ] Error handling
- [ ] Bug fixes
- [ ] Linux packaging (.deb, AppImage)

### Future (Post-MVP)
- [ ] First-run wizard
- [ ] Waveform visualization (nice-to-have)
- [ ] macOS/Windows support (v0.5+)

---

## Open Questions

1. **Floating bar vs overlay?**
   - Should the bar be a separate window or a screen overlay?
   - Overlay is more seamless but has compositor compatibility issues

2. **Auto-start behavior?**
   - Should GUI auto-start Synthia core, or expect it running?
   - Recommendation: GUI manages core lifecycle

3. **Multiple instances?**
   - Allow multiple GUI instances?
   - Recommendation: Single instance with bring-to-front

4. **Update mechanism?**
   - Self-update, package manager only, or manual?
   - Depends on distribution method

---

## Appendix

### Competitive Analysis

| Feature | Synthia GUI | Talon | Whisper.cpp GUI |
|---------|-------------|-------|-----------------|
| Floating bar | ✓ | ✓ | ✗ |
| System tray | ✓ | ✓ | ✓ |
| Waveform | ✓ | ✗ | ✗ |
| Voice history | ✓ | ✓ | ✗ |
| Cross-platform | ✓ | ✓ | ✓ |
| Open source | ✓ | ✗ | ✓ |
| Local-first | ✓ | ✓ | ✓ |

### References

- [Tauri Documentation](https://tauri.app/v1/guides/)
- [egui](https://github.com/emilk/egui)
- [iced](https://github.com/iced-rs/iced)
- [Lucide Icons](https://lucide.dev/)

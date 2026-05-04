# Knowledge Section Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the knowledge section from a vertical file-manager layout to a two-column "second brain" dashboard with a collapsible folder tree, pinned note cards with content previews, and a compact recent list.

**Architecture:** Replace the current `renderKnowledgeSection()` browser view (lines 3261-3446 in App.tsx) with a two-column layout. Left column (35%) has a compact collapsible folder tree. Right column (65%) has pinned cards with content previews and a compact recent list. Search stays full-width at top. Backend gets two new commands for note previews and modified timestamps.

**Tech Stack:** React (TypeScript), Tauri (Rust), CSS

---

### Task 1: Add Backend Commands for Note Previews and Timestamps

**Files:**
- Modify: `gui/src-tauri/src/lib.rs:2290-2542`

**Step 1: Add `get_note_preview` command**

After `read_note` (line 2414), add:

```rust
#[tauri::command]
fn get_note_preview(path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full = base.join(&path);
    if !full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }
    match std::fs::read_to_string(&full) {
        Ok(content) => {
            let preview: String = content.chars().take(200).collect();
            Ok(preview)
        }
        Err(e) => Err(e.to_string()),
    }
}
```

**Step 2: Add `get_note_modified` command**

After the new `get_note_preview`:

```rust
#[tauri::command]
fn get_note_modified(path: String) -> Result<u64, String> {
    let base = get_notes_base_path();
    let full = base.join(&path);
    if !full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }
    match std::fs::metadata(&full) {
        Ok(meta) => {
            match meta.modified() {
                Ok(time) => {
                    let duration = time.duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
                    Ok(duration.as_secs())
                }
                Err(e) => Err(e.to_string()),
            }
        }
        Err(e) => Err(e.to_string()),
    }
}
```

**Step 3: Register the new commands in the invoke_handler**

Find the `.invoke_handler(tauri::generate_handler![...])` call and add `get_note_preview, get_note_modified` to the list.

**Step 4: Extend `KnowledgeMeta` struct to support expanded folders**

Modify the struct at lines 2293-2296:

```rust
#[derive(Serialize, Deserialize, Clone)]
struct KnowledgeMeta {
    pinned: Vec<String>,
    recent: Vec<String>,
    #[serde(default)]
    expanded_folders: Vec<String>,
}
```

**Step 5: Build and verify**

Run: `cd gui && cargo build 2>&1 | tail -20`
Expected: Successful compilation

**Step 6: Commit**

```
feat(gui): add backend commands for note previews and timestamps
```

---

### Task 2: Add TypeScript Types and State for Tree View

**Files:**
- Modify: `gui/src/App.tsx:400-416` (state variables area)

**Step 1: Update KnowledgeMeta interface**

Find the `KnowledgeMeta` interface and add:

```typescript
interface KnowledgeMeta {
  pinned: string[];
  recent: string[];
  expanded_folders: string[];
}
```

**Step 2: Add new state variables**

After the existing knowledge state variables (around line 416), add:

```typescript
const [expandedFolders, setExpandedFolders] = useState<string[]>([]);
const [allNoteEntries, setAllNoteEntries] = useState<Record<string, NoteEntry[]>>({});
const [pinnedPreviews, setPinnedPreviews] = useState<Record<string, string>>({});
const [pinnedModified, setPinnedModified] = useState<Record<string, number>>({});
```

**Step 3: Update `loadKnowledgeMeta` (around line 888)**

Add loading expanded_folders from the meta:

```typescript
const loadKnowledgeMeta = async () => {
  try {
    const meta: KnowledgeMeta = await invoke("get_knowledge_meta");
    setPinnedNotes(meta.pinned || []);
    setRecentNotes(meta.recent || []);
    setExpandedFolders(meta.expanded_folders || []);
  } catch (e) {
    console.error("Failed to load knowledge meta:", e);
  }
};
```

**Step 4: Update `saveKnowledgeMeta` (around line 898)**

Include expanded_folders in the save:

```typescript
const saveKnowledgeMeta = async (
  pinned?: string[],
  recent?: string[],
  expanded?: string[]
) => {
  const meta: KnowledgeMeta = {
    pinned: pinned ?? pinnedNotes,
    recent: recent ?? recentNotes,
    expanded_folders: expanded ?? expandedFolders,
  };
  await invoke("save_knowledge_meta", { meta });
};
```

**Step 5: Add function to load previews for pinned notes**

After the save function:

```typescript
const loadPinnedPreviews = async (pinned: string[]) => {
  const previews: Record<string, string> = {};
  const modified: Record<string, number> = {};
  for (const path of pinned) {
    try {
      const preview: string = await invoke("get_note_preview", { path });
      previews[path] = preview;
      const mod: number = await invoke("get_note_modified", { path });
      modified[path] = mod;
    } catch (e) {
      previews[path] = "";
      modified[path] = 0;
    }
  }
  setPinnedPreviews(previews);
  setPinnedModified(modified);
};
```

**Step 6: Add function to load tree entries for a folder**

```typescript
const loadTreeEntries = async (subpath: string) => {
  try {
    const entries: NoteEntry[] = await invoke("list_notes", {
      subpath: subpath || null,
    });
    setAllNoteEntries((prev) => ({ ...prev, [subpath]: entries }));
  } catch (e) {
    console.error("Failed to load tree entries:", e);
  }
};
```

**Step 7: Add folder toggle handler**

```typescript
const toggleFolder = async (folderPath: string) => {
  const isExpanded = expandedFolders.includes(folderPath);
  let newExpanded: string[];
  if (isExpanded) {
    newExpanded = expandedFolders.filter((f) => f !== folderPath);
  } else {
    newExpanded = [...expandedFolders, folderPath];
    if (!allNoteEntries[folderPath]) {
      await loadTreeEntries(folderPath);
    }
  }
  setExpandedFolders(newExpanded);
  saveKnowledgeMeta(undefined, undefined, newExpanded);
};
```

**Step 8: Add relative time helper**

```typescript
const getRelativeTime = (timestamp: number): string => {
  if (!timestamp) return "";
  const now = Math.floor(Date.now() / 1000);
  const diff = now - timestamp;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return `${Math.floor(diff / 604800)}w ago`;
};
```

**Step 9: Call loaders on knowledge section mount**

In the existing useEffect that loads knowledge data (or in the section activation handler), ensure:

```typescript
// When knowledge section becomes active:
loadTreeEntries("");  // Load root folder entries
loadPinnedPreviews(pinnedNotes);
```

**Step 10: Commit**

```
feat(gui): add state management for knowledge tree view and card previews
```

---

### Task 3: Build the Folder Tree Component

**Files:**
- Modify: `gui/src/App.tsx:3261-3446` (renderKnowledgeSection browser view)

**Step 1: Create the recursive tree renderer**

Add a helper function before `renderKnowledgeSection` (or inside it):

```typescript
const renderFolderTree = (parentPath: string, depth: number = 0) => {
  const entries = allNoteEntries[parentPath] || [];
  const folders = entries.filter((e) => e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
  const files = entries.filter((e) => !e.is_dir).sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="knowledge-tree-level">
      {folders.map((folder) => {
        const isExpanded = expandedFolders.includes(folder.path);
        return (
          <div key={folder.path}>
            <button
              className="knowledge-tree-item knowledge-tree-folder"
              style={{ paddingLeft: `${12 + depth * 16}px` }}
              onClick={() => toggleFolder(folder.path)}
            >
              <span className="knowledge-tree-arrow">
                {isExpanded ? "▾" : "▸"}
              </span>
              <span className="knowledge-tree-name">{folder.name}</span>
            </button>
            {isExpanded && renderFolderTree(folder.path, depth + 1)}
          </div>
        );
      })}
      {files.map((file) => (
        <button
          key={file.path}
          className="knowledge-tree-item knowledge-tree-file"
          style={{ paddingLeft: `${28 + depth * 16}px` }}
          onClick={() => handleOpenNote(file.path)}
        >
          <span className="knowledge-tree-name">{file.name}</span>
        </button>
      ))}
    </div>
  );
};
```

**Step 2: Commit**

```
feat(gui): add recursive folder tree renderer for knowledge section
```

---

### Task 4: Rewrite the Knowledge Browser View Layout

**Files:**
- Modify: `gui/src/App.tsx:3261-3446` (the browser view portion of renderKnowledgeSection)

**Step 1: Replace the entire browser view JSX**

Replace lines 3261 through the end of the browser section (around line 3446) with the new two-column layout. Keep the editor view (lines 3161-3260) as-is.

The new browser view:

```tsx
{/* Browser View */}
{!noteEditing && (
  <div className="knowledge-dashboard">
    {/* Full-width search bar */}
    <div className="knowledge-top-bar">
      <div className="knowledge-search">
        <span className="knowledge-search-icon">🔍</span>
        <input
          type="text"
          placeholder="Search notes..."
          value={knowledgeSearch}
          onChange={(e) => setKnowledgeSearch(e.target.value)}
          className="knowledge-search-input"
        />
        {knowledgeSearch && (
          <button
            className="knowledge-search-clear"
            onClick={() => setKnowledgeSearch("")}
          >
            ✕
          </button>
        )}
      </div>
      <button
        className="knowledge-new-btn"
        onClick={() => setShowNewNote(true)}
      >
        + New
      </button>
    </div>

    {/* New note modal - keep existing */}
    {showNewNote && (
      <div className="new-note-modal">
        <input
          type="text"
          placeholder="Note or folder name..."
          value={newNoteName}
          onChange={(e) => setNewNoteName(e.target.value)}
          className="new-note-input"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter") handleCreateNote();
            if (e.key === "Escape") setShowNewNote(false);
          }}
        />
        <button className="new-note-create" onClick={handleCreateNote}>
          Note
        </button>
        <button
          className="new-note-create folder"
          onClick={handleCreateFolder}
        >
          Folder
        </button>
        <button
          className="new-note-create"
          onClick={() => setShowNewNote(false)}
          style={{ background: "rgba(100,100,100,0.3)" }}
        >
          Cancel
        </button>
      </div>
    )}

    {/* Two-column layout */}
    <div className="knowledge-columns">
      {/* Left column - folder tree */}
      <div className="knowledge-tree-panel">
        <div className="knowledge-section-label">FOLDERS</div>
        <div className="knowledge-tree-scroll">
          {renderFolderTree("")}
        </div>
      </div>

      {/* Right column - pinned cards + recent */}
      <div className="knowledge-content-panel">
        {knowledgeSearch ? (
          /* Search results */
          <div className="knowledge-search-results">
            <div className="knowledge-section-label">RESULTS</div>
            {noteEntries
              .filter((e) =>
                !e.is_dir &&
                e.name.toLowerCase().includes(knowledgeSearch.toLowerCase())
              )
              .map((entry) => (
                <button
                  key={entry.path}
                  className="knowledge-search-result-item"
                  onClick={() => handleOpenNote(entry.path)}
                >
                  <span className="knowledge-result-name">{entry.name}</span>
                  <span className="knowledge-result-path">
                    {entry.path.split("/").slice(0, -1).join(" / ")}
                  </span>
                </button>
              ))}
          </div>
        ) : (
          <>
            {/* Pinned cards */}
            {pinnedNotes.length > 0 && (
              <div className="knowledge-pinned-section">
                <div className="knowledge-section-label">PINNED</div>
                <div className="knowledge-cards-grid">
                  {pinnedNotes.map((path) => {
                    const name = path.split("/").pop() || path;
                    const preview = pinnedPreviews[path] || "";
                    const modified = pinnedModified[path] || 0;
                    return (
                      <button
                        key={path}
                        className="knowledge-card"
                        onClick={() => handleOpenNote(path)}
                      >
                        <div className="knowledge-card-title">{name.replace(/\.md$/, "")}</div>
                        <div className="knowledge-card-preview">
                          {preview.replace(/^#+ .*/gm, "").trim().slice(0, 120)}
                        </div>
                        <div className="knowledge-card-meta">
                          {getRelativeTime(modified)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Recent list */}
            {recentNotes.length > 0 && (
              <div className="knowledge-recent-section">
                <div className="knowledge-section-label">RECENT</div>
                <div className="knowledge-recent-list">
                  {recentNotes.map((path) => {
                    const name = path.split("/").pop() || path;
                    return (
                      <button
                        key={path}
                        className="knowledge-recent-item"
                        onClick={() => handleOpenNote(path)}
                      >
                        <span className="knowledge-recent-name">
                          {name.replace(/\.md$/, "")}
                        </span>
                        <span className="knowledge-recent-time">
                          {getRelativeTime(pinnedModified[path] || 0)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  </div>
)}
```

**Step 2: Update search to also search all entries recursively**

For search to work across all folders, load all file entries when search is active. Add to the search onChange handler:

```typescript
// When search starts, load a flat list of all notes
const handleSearchChange = async (query: string) => {
  setKnowledgeSearch(query);
  if (query && noteEntries.length === 0) {
    // Load root entries for search filtering
    const entries: NoteEntry[] = await invoke("list_notes", { subpath: null });
    setNoteEntries(entries);
  }
};
```

Note: Full recursive search would require a new backend command. For now, search filters the current root-level entries. This can be enhanced later.

**Step 3: Commit**

```
feat(gui): rewrite knowledge browser with two-column dashboard layout
```

---

### Task 5: Write the New CSS Styles

**Files:**
- Modify: `gui/src/App.css:1951-2103` (knowledge-specific styles section)

**Step 1: Replace knowledge-specific CSS**

Remove the old knowledge styles (lines 1951-2103) and replace with:

```css
/* ===== Knowledge Dashboard ===== */

.knowledge-dashboard {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
}

.knowledge-top-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 0 4px;
}

.knowledge-search {
  flex: 1;
  display: flex;
  align-items: center;
  background: rgba(10, 11, 20, 0.6);
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 8px;
  padding: 0 12px;
  transition: border-color 0.2s;
}

.knowledge-search:focus-within {
  border-color: rgba(6, 182, 212, 0.4);
}

.knowledge-search-icon {
  font-size: 14px;
  opacity: 0.5;
  margin-right: 8px;
}

.knowledge-search-input {
  flex: 1;
  background: none;
  border: none;
  color: #e2e8f0;
  font-size: 14px;
  padding: 10px 0;
  outline: none;
  font-family: inherit;
}

.knowledge-search-input::placeholder {
  color: #475569;
}

.knowledge-search-clear {
  background: none;
  border: none;
  color: #475569;
  cursor: pointer;
  font-size: 14px;
  padding: 4px;
}

.knowledge-search-clear:hover {
  color: #e2e8f0;
}

.knowledge-new-btn {
  background: rgba(6, 182, 212, 0.15);
  border: 1px solid rgba(6, 182, 212, 0.3);
  color: #06b6d4;
  padding: 10px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s;
}

.knowledge-new-btn:hover {
  background: rgba(6, 182, 212, 0.25);
  border-color: rgba(6, 182, 212, 0.5);
}

/* Two-column layout */
.knowledge-columns {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Left column - folder tree */
.knowledge-tree-panel {
  width: 35%;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  background: rgba(10, 11, 20, 0.4);
  border: 1px solid rgba(6, 182, 212, 0.08);
  border-radius: 8px;
  padding: 12px 0;
}

.knowledge-tree-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.knowledge-tree-scroll::-webkit-scrollbar {
  width: 4px;
}

.knowledge-tree-scroll::-webkit-scrollbar-thumb {
  background: rgba(6, 182, 212, 0.2);
  border-radius: 2px;
}

.knowledge-tree-level {
  display: flex;
  flex-direction: column;
}

.knowledge-tree-item {
  display: flex;
  align-items: center;
  width: 100%;
  background: none;
  border: none;
  color: #e2e8f0;
  font-size: 13px;
  padding: 6px 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
  gap: 6px;
}

.knowledge-tree-item:hover {
  background: rgba(6, 182, 212, 0.08);
}

.knowledge-tree-folder .knowledge-tree-name {
  color: rgba(234, 179, 8, 0.85);
}

.knowledge-tree-file .knowledge-tree-name {
  color: rgba(6, 182, 212, 0.75);
}

.knowledge-tree-arrow {
  font-size: 10px;
  width: 12px;
  color: #475569;
}

.knowledge-tree-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Right column - content */
.knowledge-content-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding-right: 4px;
}

.knowledge-content-panel::-webkit-scrollbar {
  width: 4px;
}

.knowledge-content-panel::-webkit-scrollbar-thumb {
  background: rgba(6, 182, 212, 0.2);
  border-radius: 2px;
}

/* Section labels */
.knowledge-section-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #475569;
  text-transform: uppercase;
  padding: 0 12px 8px;
}

/* Pinned cards grid */
.knowledge-pinned-section {
  display: flex;
  flex-direction: column;
}

.knowledge-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  padding: 0 4px;
}

.knowledge-card {
  display: flex;
  flex-direction: column;
  background: rgba(10, 11, 20, 0.6);
  border: 1px solid rgba(168, 85, 247, 0.15);
  border-left: 3px solid rgba(168, 85, 247, 0.5);
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
  gap: 8px;
}

.knowledge-card:hover {
  background: rgba(10, 11, 20, 0.8);
  border-color: rgba(168, 85, 247, 0.3);
  border-left-color: rgba(168, 85, 247, 0.7);
  box-shadow: 0 2px 12px rgba(168, 85, 247, 0.08);
}

.knowledge-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-card-preview {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.knowledge-card-meta {
  font-size: 11px;
  color: #475569;
  margin-top: auto;
}

/* Recent list */
.knowledge-recent-section {
  display: flex;
  flex-direction: column;
}

.knowledge-recent-list {
  display: flex;
  flex-direction: column;
}

.knowledge-recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  background: none;
  border: none;
  border-bottom: 1px solid rgba(6, 182, 212, 0.06);
  color: #e2e8f0;
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.knowledge-recent-item:hover {
  background: rgba(6, 182, 212, 0.06);
}

.knowledge-recent-item:last-child {
  border-bottom: none;
}

.knowledge-recent-name {
  font-size: 13px;
  color: #cbd5e1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-recent-time {
  font-size: 11px;
  color: #475569;
  white-space: nowrap;
  margin-left: 12px;
}

/* Search results */
.knowledge-search-results {
  display: flex;
  flex-direction: column;
}

.knowledge-search-result-item {
  display: flex;
  flex-direction: column;
  width: 100%;
  background: none;
  border: none;
  border-bottom: 1px solid rgba(6, 182, 212, 0.06);
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
  gap: 2px;
}

.knowledge-search-result-item:hover {
  background: rgba(6, 182, 212, 0.06);
}

.knowledge-result-name {
  font-size: 13px;
  color: #e2e8f0;
}

.knowledge-result-path {
  font-size: 11px;
  color: #475569;
}
```

**Step 2: Commit**

```
style(gui): add CSS for two-column knowledge dashboard layout
```

---

### Task 6: Wire Up Data Loading on Section Mount

**Files:**
- Modify: `gui/src/App.tsx` (useEffect / section activation)

**Step 1: Find where the knowledge section becomes active**

Look for where `activeSection === "knowledge"` triggers data loading. Ensure these calls happen:

```typescript
// When knowledge section activates:
loadTreeEntries("");           // Load root folder tree
loadKnowledgeMeta();           // Load pinned/recent/expanded
// Then after meta loads, load previews:
loadPinnedPreviews(pinnedNotes);
```

**Step 2: Add useEffect for loading previews when pinned changes**

```typescript
useEffect(() => {
  if (activeSection === "knowledge" && pinnedNotes.length > 0) {
    loadPinnedPreviews(pinnedNotes);
  }
}, [pinnedNotes, activeSection]);
```

**Step 3: Load expanded folders on mount**

```typescript
useEffect(() => {
  if (activeSection === "knowledge" && expandedFolders.length > 0) {
    expandedFolders.forEach((folder) => loadTreeEntries(folder));
  }
}, [activeSection]);
```

**Step 4: Build and test**

Run: `cd gui && npm run dev`
Verify: Knowledge section shows two-column layout with tree on left, cards on right

**Step 5: Commit**

```
feat(gui): wire up data loading for knowledge dashboard
```

---

### Task 7: Clean Up Old Code and Test

**Files:**
- Modify: `gui/src/App.tsx` (remove dead code)
- Modify: `gui/src/App.css` (remove orphaned styles)

**Step 1: Remove old browse-related state if no longer needed**

Check if `notesPath` state is still needed (used for breadcrumb navigation in old layout). The tree view doesn't use breadcrumb navigation, but the editor view might still use `notesPath` for context. Keep it if the editor references it; remove if not.

**Step 2: Remove orphaned CSS**

Remove old styles that are no longer referenced:
- `.knowledge-pinned-grid` (replaced by `.knowledge-cards-grid`)
- `.knowledge-pinned-card` (replaced by `.knowledge-card`)
- Old `.knowledge-search` if fully replaced
- Any breadcrumb styles only used in the browse section (keep if editor uses them)

**Step 3: Test all interactions**

- Open knowledge section → see two-column layout
- Expand/collapse folders in tree → works, persists
- Click file in tree → opens editor
- View pinned cards → shows title, preview, timestamp
- Click pinned card → opens editor
- Click recent item → opens editor
- Search → shows filtered results in right column
- Create new note → works
- Pin/unpin from editor → card appears/disappears

**Step 4: Commit**

```
refactor(gui): clean up old knowledge section code
```

---

### Task 8: Build and Verify

**Step 1: Run full build**

```bash
cd gui && npm run build && cargo build
```

**Step 2: Test the built application**

```bash
cd gui && cargo tauri dev
```

**Step 3: Verify all functionality works end-to-end**

**Step 4: Final commit**

```
chore(gui): verify knowledge section redesign build
```

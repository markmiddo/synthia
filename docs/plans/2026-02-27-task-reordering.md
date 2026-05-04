# Task Reordering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable drag-and-drop reordering of tasks within kanban columns, with persistent sort order.

**Architecture:** Add a `sort_order: f64` field to the Task model. Within-column drag-and-drop calculates a midpoint sort_order between neighboring tasks. A new `reorder_task` Tauri command persists the change. Existing tasks get sort_order assigned on first load (migration).

**Tech Stack:** Rust (Tauri backend), React/TypeScript (frontend), HTML5 drag-and-drop API (already in use)

---

### Task 1: Add sort_order to Rust Task struct and migration

**Files:**
- Modify: `gui/src-tauri/src/lib.rs:1969-1979` (Task struct)
- Modify: `gui/src-tauri/src/lib.rs:1993-2000` (load_tasks)
- Modify: `gui/src-tauri/src/lib.rs:2011-2014` (list_tasks)
- Modify: `gui/src-tauri/src/lib.rs:2025-2034` (add_task)

**Step 1: Add sort_order field to Task struct**

In `lib.rs` at the Task struct (line 1969), add `sort_order` as an `Option<f64>` with a serde default so existing JSON without the field deserializes correctly:

```rust
#[derive(Deserialize, Serialize, Debug, Clone)]
struct Task {
    id: String,
    title: String,
    description: Option<String>,
    status: String,
    tags: Vec<String>,
    due_date: Option<String>,
    created_at: String,
    completed_at: Option<String>,
    #[serde(default)]
    sort_order: Option<f64>,
}
```

**Step 2: Add migration in load_tasks**

Replace `load_tasks()` (line 1993) to assign `sort_order` to any task missing it and save back:

```rust
fn load_tasks() -> TasksData {
    let path = get_tasks_file();
    if let Ok(content) = fs::read_to_string(&path) {
        let mut data: TasksData = serde_json::from_str(&content).unwrap_or_default();
        let mut needs_save = false;
        for (i, task) in data.tasks.iter_mut().enumerate() {
            if task.sort_order.is_none() {
                task.sort_order = Some((i as f64 + 1.0) * 1000.0);
                needs_save = true;
            }
        }
        if needs_save {
            let _ = save_tasks(&data);
        }
        data
    } else {
        TasksData::default()
    }
}
```

**Step 3: Sort in list_tasks**

Replace `list_tasks` (line 2011) to return tasks sorted by sort_order:

```rust
#[tauri::command]
fn list_tasks() -> Vec<Task> {
    let mut tasks = load_tasks().tasks;
    tasks.sort_by(|a, b| {
        a.sort_order.unwrap_or(0.0)
            .partial_cmp(&b.sort_order.unwrap_or(0.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    tasks
}
```

**Step 4: Set sort_order on new tasks**

In `add_task` (line 2025), add sort_order to the new Task. Use a large value so new tasks appear at the bottom of their column:

```rust
let max_order = data.tasks.iter()
    .filter_map(|t| t.sort_order)
    .fold(0.0_f64, f64::max);

let task = Task {
    id: uuid::Uuid::new_v4().to_string(),
    title,
    description,
    status: "todo".to_string(),
    tags,
    due_date,
    created_at: chrono::Utc::now().to_rfc3339(),
    completed_at: None,
    sort_order: Some(max_order + 1000.0),
};
```

**Step 5: Compile and verify**

Run: `cd gui && cargo build 2>&1 | head -30` from `src-tauri/`
Expected: Compiles without errors (warnings OK)

**Step 6: Commit**

```
feat(gui): add sort_order field to Task model with migration
```

---

### Task 2: Add reorder_task Tauri command

**Files:**
- Modify: `gui/src-tauri/src/lib.rs:2096-2099` (after move_task)
- Modify: `gui/src-tauri/src/lib.rs:2976` (invoke_handler registration)

**Step 1: Add the reorder_task command**

Insert after `move_task` (line 2099):

```rust
#[tauri::command]
fn reorder_task(id: String, sort_order: f64) -> Result<Task, String> {
    let mut data = load_tasks();
    let task = data.tasks.iter_mut()
        .find(|t| t.id == id)
        .ok_or("Task not found")?;
    task.sort_order = Some(sort_order);
    let updated = task.clone();
    save_tasks(&data)?;
    Ok(updated)
}
```

**Step 2: Register the command**

In the invoke_handler (line 2976), add `reorder_task` after `move_task`:

```
            move_task,
            reorder_task,
```

**Step 3: Compile and verify**

Run: `cd gui/src-tauri && cargo build 2>&1 | head -30`
Expected: Compiles without errors

**Step 4: Commit**

```
feat(gui): add reorder_task Tauri command
```

---

### Task 3: Update TypeScript Task interface and add sort_order to frontend

**Files:**
- Modify: `gui/src/App.tsx:338-347` (Task interface)
- Modify: `gui/src/App.tsx:435-444` (state variables)

**Step 1: Add sort_order to TypeScript interface**

Update the Task interface (line 338):

```typescript
interface Task {
  id: string;
  title: string;
  description?: string;
  status: "todo" | "in_progress" | "done";
  tags: string[];
  due_date?: string;
  created_at: string;
  completed_at?: string;
  sort_order?: number;
}
```

**Step 2: Add drag-within-column state**

After the existing `dragOverColumn` state (line 444), add:

```typescript
const [dragOverTaskId, setDragOverTaskId] = useState<string | null>(null);
const [dragOverPosition, setDragOverPosition] = useState<"above" | "below" | null>(null);
```

**Step 3: Add reorder handler**

After `handleDeleteTask` (line 1101), add:

```typescript
async function handleReorderTask(id: string, sortOrder: number) {
  try {
    await invoke("reorder_task", { id, sortOrder });
    loadTasks();
  } catch (e) {
    setError(String(e));
  }
}
```

**Step 4: Commit**

```
feat(gui): add sort_order to TypeScript Task interface and reorder handler
```

---

### Task 4: Implement within-column drag-and-drop

**Files:**
- Modify: `gui/src/App.tsx:2981-3030` (renderTasksSection and renderTaskCard)

**Step 1: Sort tasks within each column**

Replace the column filtering (line 2982-2984) with sorted versions:

```typescript
const sortTasks = (t: Task[]) => [...t].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
const todoTasks = sortTasks(tasks.filter(t => t.status === "todo"));
const inProgressTasks = sortTasks(tasks.filter(t => t.status === "in_progress"));
const doneTasks = sortTasks(tasks.filter(t => t.status === "done"));
```

**Step 2: Update renderTaskCard for within-column drag detection**

Replace `renderTaskCard` (lines 2997-3030) to add `onDragOver` to each card that detects whether the cursor is in the top or bottom half, and store the task ID + position. Also render a visual drop indicator:

```typescript
function renderTaskCard(task: Task, columnTasks: Task[]) {
  const isDropTarget = dragOverTaskId === task.id && draggedTaskId !== task.id;
  return (
    <div key={task.id}>
      {isDropTarget && dragOverPosition === "above" && (
        <div className="task-drop-indicator" />
      )}
      <div
        className={`task-card ${draggedTaskId === task.id ? "dragging" : ""}`}
        onClick={() => setEditingTask(task)}
        draggable
        onDragStart={(e) => {
          setDraggedTaskId(task.id);
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", task.id);
          e.dataTransfer.setData("application/x-task-status", task.status);
        }}
        onDragEnd={() => {
          setDraggedTaskId(null);
          setDragOverColumn(null);
          setDragOverTaskId(null);
          setDragOverPosition(null);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          const rect = e.currentTarget.getBoundingClientRect();
          const midY = rect.top + rect.height / 2;
          setDragOverTaskId(task.id);
          setDragOverPosition(e.clientY < midY ? "above" : "below");
        }}
        onDragLeave={() => {
          setDragOverTaskId(null);
          setDragOverPosition(null);
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          const taskId = e.dataTransfer.getData("text/plain");
          const sourceStatus = e.dataTransfer.getData("application/x-task-status");
          if (!taskId || taskId === task.id) return;

          const idx = columnTasks.findIndex(t => t.id === task.id);
          const insertIdx = dragOverPosition === "below" ? idx + 1 : idx;

          // Calculate new sort_order
          const prev = insertIdx > 0 ? columnTasks[insertIdx - 1] : null;
          const next = insertIdx < columnTasks.length ? columnTasks[insertIdx] : null;
          // Skip the dragged task itself when calculating neighbors
          const prevOrder = prev && prev.id !== taskId ? (prev.sort_order ?? 0) : null;
          const nextOrder = next && next.id !== taskId ? (next.sort_order ?? 0) : null;

          let newOrder: number;
          if (prevOrder !== null && nextOrder !== null) {
            newOrder = (prevOrder + nextOrder) / 2;
          } else if (prevOrder !== null) {
            newOrder = prevOrder + 1000;
          } else if (nextOrder !== null) {
            newOrder = nextOrder - 1000;
          } else {
            newOrder = 1000;
          }

          // If cross-column, move first then reorder
          if (sourceStatus !== task.status) {
            handleMoveTask(taskId, task.status).then(() => {
              handleReorderTask(taskId, newOrder);
            });
          } else {
            handleReorderTask(taskId, newOrder);
          }

          setDragOverTaskId(null);
          setDragOverPosition(null);
          setDragOverColumn(null);
        }}
      >
        <div className="task-card-title">{task.title}</div>
        {task.description && (
          <div className="task-card-desc">{task.description}</div>
        )}
        <div className="task-card-meta">
          {task.due_date && (
            <span className={`task-due ${isOverdue(task.due_date) && task.status !== "done" ? "overdue" : ""}`}>
              {formatDate(task.due_date)}
            </span>
          )}
          {task.tags.map(tag => {
            const color = getTagColor(tag);
            return (
              <span key={tag} className="task-tag" style={{ background: color.bg, color: color.text }}>{tag}</span>
            );
          })}
        </div>
      </div>
      {isDropTarget && dragOverPosition === "below" && (
        <div className="task-drop-indicator" />
      )}
    </div>
  );
}
```

**Step 3: Update column rendering to pass columnTasks**

In each kanban column's content div, change from:

```typescript
{todoTasks.map(renderTaskCard)}
```

to:

```typescript
{todoTasks.map(t => renderTaskCard(t, todoTasks))}
```

Do the same for `inProgressTasks` and `doneTasks`.

**Step 4: Commit**

```
feat(gui): implement within-column drag-and-drop reordering
```

---

### Task 5: Add drop indicator CSS

**Files:**
- Modify: `gui/src/App.css` (after `.task-card.dragging` around line 2295)

**Step 1: Add drop indicator styles**

After the `.task-card.dragging` rule, add:

```css
.task-drop-indicator {
  height: 3px;
  background: #6366f1;
  border-radius: 2px;
  margin: 2px 0;
  transition: opacity 0.15s;
}
```

**Step 2: Build and test visually**

Run: `cd gui && npm run dev`
Test: Create 3+ tasks in the "To Do" column, drag one between the others. Verify:
- A purple line appears at the insertion point
- The task moves to the new position after dropping
- Refreshing the page preserves the new order
- Cross-column drag still works correctly

**Step 3: Commit**

```
style(gui): add task reorder drop indicator
```

---

### Task 6: Handle column-level drop for empty columns and bottom-of-column drops

**Files:**
- Modify: `gui/src/App.tsx:3167-3224` (kanban column drop handlers)

**Step 1: Update column onDrop handlers**

The existing column-level `onDrop` currently just calls `handleMoveTask`. We need to also handle the case where a task is dropped onto the empty space at the bottom of its own column (reorder to end) or into an empty column. Update each column's `onDrop` handler to calculate a sort_order for the end of the column.

For the "todo" column (and similarly for "in_progress" and "done"), replace the `onDrop`:

```typescript
onDrop={(e) => {
  e.preventDefault();
  const taskId = e.dataTransfer.getData("text/plain");
  const sourceStatus = e.dataTransfer.getData("application/x-task-status");
  if (!taskId) return;

  // If dropped on column background (not on a card), place at end
  const columnTasks = todoTasks; // use inProgressTasks / doneTasks for other columns
  const lastOrder = columnTasks.length > 0
    ? Math.max(...columnTasks.filter(t => t.id !== taskId).map(t => t.sort_order ?? 0))
    : 0;
  const newOrder = lastOrder + 1000;

  if (sourceStatus !== "todo") {
    handleMoveTask(taskId, "todo").then(() => {
      handleReorderTask(taskId, newOrder);
    });
  } else {
    handleReorderTask(taskId, newOrder);
  }

  setDragOverColumn(null);
  setDragOverTaskId(null);
  setDragOverPosition(null);
}}
```

Repeat the same pattern for the "in_progress" and "done" columns, using their respective `columnTasks` variable and status string.

**Step 2: Verify empty column behavior**

Test: Move all tasks out of a column, then drag one back in. It should appear with a valid sort_order.

**Step 3: Commit**

```
feat(gui): handle column-level drops with sort ordering
```

---

### Task 7: Final integration test and cleanup

**Step 1: Build the Tauri app**

Run: `cd gui/src-tauri && cargo build`
Expected: Clean compile

**Step 2: Manual integration test**

Run: `cd gui && npm run dev`

Test these scenarios:
1. Existing tasks get sort_order assigned (check `~/.config/synthia/tasks.json`)
2. New task appears at bottom of "To Do" column
3. Drag task within column - reorders and persists across refresh
4. Drag task between columns - status changes and sort_order is set
5. Drag to empty column works
6. Drop indicator appears correctly during drag
7. Editing/deleting tasks still works

**Step 3: Commit**

```
feat(gui): task reordering - integration verified
```

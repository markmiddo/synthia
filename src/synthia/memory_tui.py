"""TUI Dashboard for Memory System using Textual.

Launch with: synthia-memory

Features:
- Browse/search memories
- Edit entries
- Delete entries
- Keyboard navigation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TextArea,
)

from synthia.memory import (
    MEMORY_CATEGORIES,
    MemoryEntry,
    MemorySystem,
    get_memory_system,
)


class EditScreen(ModalScreen[Optional[dict]]):
    """Modal screen for editing a memory entry."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    EditScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 80%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
        color: $primary;
    }

    #tags-input {
        margin-top: 1;
    }

    #button-row {
        margin-top: 2;
        height: auto;
    }

    #button-row Button {
        margin-right: 2;
    }

    TextArea {
        height: 4;
    }
    """

    def __init__(self, entry: MemoryEntry, line_number: int):
        super().__init__()
        self.entry = entry
        self.line_number = line_number
        self.fields: dict = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog"):
            yield Label(f"Edit {self.entry.category.upper()} Entry", id="edit-title")

            # Create fields based on category
            if self.entry.category == "bug":
                yield Label("Error:", classes="field-label")
                yield TextArea(self.entry.data.get("error", ""), id="field-error")
                yield Label("Cause:", classes="field-label")
                yield TextArea(self.entry.data.get("cause", ""), id="field-cause")
                yield Label("Fix:", classes="field-label")
                yield TextArea(self.entry.data.get("fix", ""), id="field-fix")
            elif self.entry.category == "pattern":
                yield Label("Topic:", classes="field-label")
                yield TextArea(self.entry.data.get("topic", ""), id="field-topic")
                yield Label("Rule:", classes="field-label")
                yield TextArea(self.entry.data.get("rule", ""), id="field-rule")
                yield Label("Why:", classes="field-label")
                yield TextArea(self.entry.data.get("why", ""), id="field-why")
            elif self.entry.category == "arch":
                yield Label("Decision:", classes="field-label")
                yield TextArea(self.entry.data.get("decision", ""), id="field-decision")
                yield Label("Why:", classes="field-label")
                yield TextArea(self.entry.data.get("why", ""), id="field-why")
            elif self.entry.category == "gotcha":
                yield Label("Area:", classes="field-label")
                yield TextArea(self.entry.data.get("area", ""), id="field-area")
                yield Label("Gotcha:", classes="field-label")
                yield TextArea(self.entry.data.get("gotcha", ""), id="field-gotcha")
            elif self.entry.category == "stack":
                yield Label("Tool:", classes="field-label")
                yield TextArea(self.entry.data.get("tool", ""), id="field-tool")
                yield Label("Note:", classes="field-label")
                yield TextArea(self.entry.data.get("note", ""), id="field-note")

            yield Label("Tags (comma-separated):", classes="field-label")
            yield Input(", ".join(self.entry.tags), id="tags-input")

            with Horizontal(id="button-row"):
                yield Button("Save (Ctrl+S)", id="save-btn", variant="primary")
                yield Button("Cancel (Esc)", id="cancel-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._do_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._do_save()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _do_save(self) -> None:
        """Collect field values and save."""
        data = {}

        # Collect fields based on category
        field_ids = {
            "bug": ["error", "cause", "fix"],
            "pattern": ["topic", "rule", "why"],
            "arch": ["decision", "why"],
            "gotcha": ["area", "gotcha"],
            "stack": ["tool", "note"],
        }

        for field_name in field_ids.get(self.entry.category, []):
            try:
                textarea = self.query_one(f"#field-{field_name}", TextArea)
                data[field_name] = textarea.text
            except Exception:
                pass

        # Get tags
        try:
            tags_input = self.query_one("#tags-input", Input)
            tags = [t.strip() for t in tags_input.value.split(",") if t.strip()]
        except Exception:
            tags = self.entry.tags

        self.dismiss({
            "category": self.entry.category,
            "data": data,
            "tags": tags,
            "line_number": self.line_number,
        })


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Confirm deletion modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes, Delete"),
        Binding("n", "cancel", "No"),
    ]

    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: 10;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #confirm-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #button-row {
        margin-top: 1;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, entry: MemoryEntry):
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Delete Entry?", id="confirm-title")
            yield Static(f"Category: {self.entry.category}")
            with Horizontal(id="button-row"):
                yield Button("Yes (Y)", id="yes-btn", variant="error")
                yield Button("No (N)", id="no-btn", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")


class MemoryListItem(ListItem):
    """Custom list item for memory entries."""

    def __init__(self, entry: MemoryEntry, line_number: int):
        super().__init__()
        self.entry = entry
        self.line_number = line_number

    def compose(self) -> ComposeResult:
        # Create a compact display
        if self.entry.category == "bug":
            text = f"[BUG] {self.entry.data.get('error', 'N/A')[:60]}"
        elif self.entry.category == "pattern":
            text = f"[PATTERN] {self.entry.data.get('topic', 'N/A')[:60]}"
        elif self.entry.category == "arch":
            text = f"[ARCH] {self.entry.data.get('decision', 'N/A')[:60]}"
        elif self.entry.category == "gotcha":
            text = f"[GOTCHA] {self.entry.data.get('area', 'N/A')[:60]}"
        elif self.entry.category == "stack":
            text = f"[STACK] {self.entry.data.get('tool', 'N/A')[:60]}"
        else:
            text = f"[{self.entry.category.upper()}] Unknown"

        yield Label(text)


class MemoryDashboard(App):
    """TUI Dashboard for Claude Memory System."""

    CSS = """
    Screen {
        background: $surface;
    }

    .section-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    .button-row {
        height: auto;
        margin: 1 0;
    }

    .button-row Button {
        margin-right: 1;
    }

    #stats-panel {
        width: 30;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }

    #main-panel {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    #results-list {
        height: 1fr;
        border: solid $secondary;
        margin-top: 1;
    }

    #detail-panel {
        height: 12;
        border: solid $accent;
        margin-top: 1;
        padding: 1;
    }

    #search-input {
        margin-bottom: 1;
    }

    #status-bar {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "focus_search", "Search"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("enter", "view_selected", "View"),
        Binding("escape", "clear_selection", "Clear"),
    ]

    TITLE = "Claude Memory Dashboard"

    def __init__(self):
        super().__init__()
        self.current_entries: list[tuple[MemoryEntry, int]] = []
        self.selected_index: int = -1
        self.active_filter: str = ""  # Track which filter button is active
        self._pending_delete: Optional[tuple[str, int]] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Label("Memory Statistics", classes="section-title"),
                Static(id="stats-content"),
                Label("Popular Tags", classes="section-title"),
                Static(id="tags-content"),
                id="stats-panel",
            ),
            Vertical(
                Label("Search Memories", classes="section-title"),
                Input(placeholder="Tags or text (Enter to search)...", id="search-input"),
                Horizontal(
                    Button("Search", id="btn-search"),
                    Button("Bugs", id="btn-bugs"),
                    Button("Patterns", id="btn-patterns"),
                    Button("Gotchas", id="btn-gotchas"),
                    Button("All", id="btn-all"),
                    classes="button-row",
                ),
                ListView(id="results-list"),
                Static("Select an entry to view details", id="detail-panel"),
                id="main-panel",
            ),
        )
        yield Static("Ready | [s]earch [e]dit [d]elete [r]efresh [q]uit", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.load_stats()
        self.load_tags()

    @work(thread=True)
    def load_stats(self) -> None:
        """Load stats in background thread."""
        mem = get_memory_system()
        counts = mem.list_categories()
        total = sum(counts.values())

        lines = [f"Total entries: {total}", ""]
        for cat, count in counts.items():
            lines.append(f"  {cat}: {count}")

        self.call_from_thread(self._update_stats, "\n".join(lines))

    def _update_stats(self, text: str) -> None:
        self.query_one("#stats-content", Static).update(text)

    @work(thread=True)
    def load_tags(self) -> None:
        """Load tags in background thread."""
        mem = get_memory_system()
        tags = mem.list_all_tags()

        lines = []
        for tag, count in list(tags.items())[:15]:
            lines.append(f"  {tag} ({count})")

        if not lines:
            lines = ["  No tags yet"]

        self.call_from_thread(self._update_tags, "\n".join(lines))

    def _update_tags(self, text: str) -> None:
        self.query_one("#tags-content", Static).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in search input."""
        if event.input.id == "search-input":
            self.do_search(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        self._set_active_button(button_id)

        if button_id == "btn-search":
            query = self.query_one("#search-input", Input).value
            self.do_search(query)
        elif button_id == "btn-bugs":
            self.load_category("bug")
        elif button_id == "btn-patterns":
            self.load_category("pattern")
        elif button_id == "btn-gotchas":
            self.load_category("gotcha")
        elif button_id == "btn-all":
            self.load_all()

    def _set_active_button(self, active_id: str) -> None:
        """Update button variants to show which is active."""
        button_ids = ["btn-search", "btn-bugs", "btn-patterns", "btn-gotchas", "btn-all"]
        for btn_id in button_ids:
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                btn.variant = "primary" if btn_id == active_id else "default"
            except Exception:
                pass

    @work(thread=True)
    def do_search(self, query: str) -> None:
        """Search in background thread."""
        if not query.strip():
            return

        mem = get_memory_system()

        # Try tag search first, then text search
        tags = [t.strip() for t in query.split(",")]
        entries = mem.recall(tags, limit=50)

        if not entries:
            entries = mem.search_text(query, limit=50)

        # Convert to list with line numbers (approximated)
        results = [(e, i) for i, e in enumerate(entries)]
        self.call_from_thread(self._display_results, results, f"Search: {query}")

    @work(thread=True)
    def load_category(self, category: str) -> None:
        """Load category in background thread."""
        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES.get(category, "")

        entries = []
        if filepath.exists():
            with open(filepath, "r") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            entry = MemoryEntry.from_dict(category, data)
                            entries.append((entry, i))
                        except json.JSONDecodeError:
                            pass

        self.call_from_thread(self._display_results, entries, f"Category: {category}")

    @work(thread=True)
    def load_all(self) -> None:
        """Load all entries in background."""
        mem = get_memory_system()
        all_entries = []

        for cat, filename in MEMORY_CATEGORIES.items():
            filepath = mem.memory_dir / filename
            if filepath.exists():
                with open(filepath, "r") as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                entry = MemoryEntry.from_dict(cat, data)
                                all_entries.append((entry, i))
                            except json.JSONDecodeError:
                                pass

        self.call_from_thread(self._display_results, all_entries, "All Entries")

    def _display_results(self, entries: list[tuple[MemoryEntry, int]], title: str) -> None:
        """Display results in the list view."""
        self.current_entries = entries
        list_view = self.query_one("#results-list", ListView)
        list_view.clear()

        for entry, line_num in entries:
            list_view.append(MemoryListItem(entry, line_num))

        self._set_status(f"{title} | {len(entries)} results")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list item selection (click or Enter)."""
        if isinstance(event.item, MemoryListItem):
            self._show_detail(event.item.entry)
            self.selected_index = event.list_view.index or 0

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle list item highlight (mouse hover or arrow keys)."""
        if isinstance(event.item, MemoryListItem):
            self._show_detail(event.item.entry)
            self.selected_index = event.list_view.index or 0

    def _show_detail(self, entry: MemoryEntry) -> None:
        """Show entry details in the detail panel."""
        detail = self.query_one("#detail-panel", Static)
        detail.update(entry.format_display())

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_refresh(self) -> None:
        self.load_stats()
        self.load_tags()
        self._set_status("Refreshed")

    def action_clear_selection(self) -> None:
        self.query_one("#detail-panel", Static).update("Select an entry to view details")
        self.selected_index = -1

    def action_view_selected(self) -> None:
        """View the selected entry."""
        if self.selected_index >= 0 and self.selected_index < len(self.current_entries):
            entry, _ = self.current_entries[self.selected_index]
            self._show_detail(entry)

    def action_edit_selected(self) -> None:
        """Edit the selected entry."""
        if self.selected_index < 0 or self.selected_index >= len(self.current_entries):
            self._set_status("No entry selected")
            return

        entry, line_num = self.current_entries[self.selected_index]
        self.push_screen(EditScreen(entry, line_num), self._on_edit_complete)

    def _on_edit_complete(self, result: Optional[dict]) -> None:
        """Callback when edit screen is dismissed."""
        if result:
            self._save_edit(result)

    def _save_edit(self, result: dict) -> None:
        """Save the edited entry."""
        category = result["category"]
        line_number = result["line_number"]
        new_data = result["data"]
        new_tags = result["tags"]

        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES[category]

        # Read all lines
        with open(filepath, "r") as f:
            lines = f.readlines()

        # Update the specific line
        if 0 <= line_number < len(lines):
            entry = MemoryEntry(category=category, data=new_data, tags=new_tags)
            lines[line_number] = json.dumps(entry.to_dict()) + "\n"

            # Write back
            with open(filepath, "w") as f:
                f.writelines(lines)

            self._set_status(f"Saved {category} entry")
            self.load_stats()
        else:
            self._set_status("Error: Could not save (line number mismatch)")

    def action_delete_selected(self) -> None:
        """Delete the selected entry."""
        if self.selected_index < 0 or self.selected_index >= len(self.current_entries):
            self._set_status("No entry selected")
            return

        entry, line_num = self.current_entries[self.selected_index]
        # Store for callback
        self._pending_delete = (entry.category, line_num)
        self.push_screen(ConfirmDeleteScreen(entry), self._on_delete_confirm)

    def _on_delete_confirm(self, confirmed: bool) -> None:
        """Callback when delete confirmation is dismissed."""
        if confirmed and hasattr(self, '_pending_delete'):
            category, line_num = self._pending_delete
            self._do_delete(category, line_num)
        self._pending_delete = None

    def _do_delete(self, category: str, line_number: int) -> None:
        """Delete an entry from the file."""
        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES[category]

        with open(filepath, "r") as f:
            lines = f.readlines()

        if 0 <= line_number < len(lines):
            del lines[line_number]

            with open(filepath, "w") as f:
                f.writelines(lines)

            self._set_status(f"Deleted {category} entry")

            # Remove from current entries
            self.current_entries.pop(self.selected_index)

            # Refresh list view
            list_view = self.query_one("#results-list", ListView)
            list_view.clear()
            for entry, ln in self.current_entries:
                list_view.append(MemoryListItem(entry, ln))

            self.selected_index = -1
            self.load_stats()
        else:
            self._set_status("Error: Could not delete")

    def _set_status(self, text: str) -> None:
        """Update status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(f"{text} | [s]earch [e]dit [d]elete [r]efresh [q]uit")


def main():
    """Run the memory dashboard."""
    app = MemoryDashboard()
    app.run()


if __name__ == "__main__":
    main()

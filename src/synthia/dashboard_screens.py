"""Modal screens for Synthia Dashboard editing."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from synthia.config_manager import AgentConfig, CommandConfig, HookConfig


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Generic delete confirmation modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
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

    def __init__(self, item_name: str):
        super().__init__()
        self.item_name = item_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Delete?", id="confirm-title")
            yield Static(f"Delete: {self.item_name}")
            with Horizontal(id="button-row"):
                yield Button("Yes (Y)", id="yes-btn", variant="error")
                yield Button("No (N)", id="no-btn", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")


class EditAgentScreen(ModalScreen[Optional[AgentConfig]]):
    """Modal for editing an agent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    EditAgentScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 85%;
        height: 85%;
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

    .field-row {
        height: 3;
    }

    .field-row Input {
        width: 1fr;
    }

    .field-row Select {
        width: 20;
    }

    #body-area {
        height: 1fr;
        margin-top: 1;
    }

    #button-row {
        margin-top: 1;
        height: 3;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, agent: Optional[AgentConfig] = None):
        super().__init__()
        self.agent = agent or AgentConfig(
            filename="new-agent.md",
            name="new-agent",
            description="",
            model="sonnet",
            color="green",
            body="",
        )
        self.is_new = agent is None

    def compose(self) -> ComposeResult:
        title = "New Agent" if self.is_new else f"Edit: {self.agent.name}"
        with Vertical(id="edit-dialog"):
            yield Label(title, id="edit-title")

            yield Label("Name:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(self.agent.name, id="name-input")

            yield Label("Description:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(self.agent.description, id="desc-input")

            yield Label("Model / Color:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Select(
                    [(m, m) for m in ["sonnet", "opus", "haiku"]],
                    value=self.agent.model,
                    id="model-select",
                )
                yield Select(
                    [(c, c) for c in ["green", "blue", "red", "yellow", "purple"]],
                    value=self.agent.color,
                    id="color-select",
                )

            yield Label("Content:", classes="field-label")
            yield TextArea(self.agent.body, id="body-area")

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
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return

        desc = self.query_one("#desc-input", Input).value
        model = self.query_one("#model-select", Select).value
        color = self.query_one("#color-select", Select).value
        body = self.query_one("#body-area", TextArea).text

        filename = f"{name}.md" if self.is_new else self.agent.filename

        result = AgentConfig(
            filename=filename,
            name=name,
            description=desc,
            model=model or "sonnet",
            color=color or "green",
            body=body,
        )
        self.dismiss(result)


class EditCommandScreen(ModalScreen[Optional[CommandConfig]]):
    """Modal for editing a command."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    EditCommandScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 85%;
        height: 85%;
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

    #body-area {
        height: 1fr;
        margin-top: 1;
    }

    #button-row {
        margin-top: 1;
        height: 3;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, command: Optional[CommandConfig] = None):
        super().__init__()
        self.command = command or CommandConfig(
            filename="new-command.md",
            description="",
            body="",
        )
        self.is_new = command is None

    def compose(self) -> ComposeResult:
        name = self.command.filename.replace(".md", "")
        title = "New Command" if self.is_new else f"Edit: /{name}"
        with Vertical(id="edit-dialog"):
            yield Label(title, id="edit-title")

            yield Label("Name (without .md):", classes="field-label")
            yield Input(name, id="name-input")

            yield Label("Description:", classes="field-label")
            yield Input(self.command.description, id="desc-input")

            yield Label("Content:", classes="field-label")
            yield TextArea(self.command.body, id="body-area")

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
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return

        desc = self.query_one("#desc-input", Input).value
        body = self.query_one("#body-area", TextArea).text

        filename = f"{name}.md"

        result = CommandConfig(
            filename=filename,
            description=desc,
            body=body,
        )
        self.dismiss(result)


class HelpScreen(ModalScreen[None]):
    """Help overlay showing keyboard shortcuts."""

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("?", "dismiss_screen", "Close"),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }

    #help-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    .help-section {
        margin-top: 1;
        color: $secondary;
    }

    .help-item {
        margin-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Synthia Dashboard Help", id="help-title")

            yield Label("Navigation:", classes="help-section")
            yield Static("  1-6    Switch sections", classes="help-item")
            yield Static("  ↑/↓    Move in list", classes="help-item")
            yield Static("  Tab    Cycle memory filters", classes="help-item")

            yield Label("Actions:", classes="help-section")
            yield Static("  e      Edit selected item", classes="help-item")
            yield Static("  n      New item", classes="help-item")
            yield Static("  d      Delete selected item", classes="help-item")
            yield Static("  Space  Toggle plugin", classes="help-item")

            yield Label("General:", classes="help-section")
            yield Static("  r      Refresh", classes="help-item")
            yield Static("  ?      Show this help", classes="help-item")
            yield Static("  q      Quit", classes="help-item")

            yield Static("")
            yield Button("Close (Esc)", id="close-btn", variant="primary")

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

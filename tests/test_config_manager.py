"""Tests for synthia.config_manager module."""

import json
from pathlib import Path

import pytest

from synthia import config_manager
from synthia.config_manager import (
    AgentConfig,
    CommandConfig,
    HookConfig,
    PluginInfo,
    delete_agent,
    delete_command,
    delete_hook,
    list_agents,
    list_commands,
    list_hooks,
    list_plugins,
    load_agent,
    load_command,
    load_settings,
    parse_frontmatter,
    save_agent,
    save_command,
    save_hook,
    save_settings,
    set_plugin_enabled,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AGENT_MD_TEMPLATE = """\
---
name: {name}
description: {description}
model: {model}
color: {color}
---

{body}"""


COMMAND_MD_TEMPLATE = """\
---
description: {description}
---

{body}"""


def _write_agent(agents_dir: Path, filename: str, **kwargs) -> Path:
    """Write a fake agent markdown file and return its path."""
    defaults = {
        "name": "Test Agent",
        "description": "A test agent",
        "model": "sonnet",
        "color": "blue",
        "body": "You are a test agent.",
    }
    defaults.update(kwargs)
    filepath = agents_dir / filename
    filepath.write_text(AGENT_MD_TEMPLATE.format(**defaults))
    return filepath


def _write_command(commands_dir: Path, filename: str, **kwargs) -> Path:
    """Write a fake command markdown file and return its path."""
    defaults = {
        "description": "A test command",
        "body": "Run the tests please.",
    }
    defaults.update(kwargs)
    filepath = commands_dir / filename
    filepath.write_text(COMMAND_MD_TEMPLATE.format(**defaults))
    return filepath


def _write_settings(settings_file: Path, data: dict) -> None:
    """Write a settings.json file."""
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    """Set up a temporary .claude directory and redirect module-level paths."""
    claude = tmp_path / ".claude"
    claude.mkdir()

    agents = claude / "agents"
    agents.mkdir()

    commands = claude / "commands"
    commands.mkdir()

    settings_file = claude / "settings.json"

    plugins_dir = claude / "plugins"
    plugins_dir.mkdir()

    # Redirect the module-level path constants
    monkeypatch.setattr(config_manager, "CLAUDE_DIR", claude)
    monkeypatch.setattr(config_manager, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(config_manager, "AGENTS_DIR", agents)
    monkeypatch.setattr(config_manager, "COMMANDS_DIR", commands)
    monkeypatch.setattr(config_manager, "PLUGINS_FILE", plugins_dir / "installed_plugins.json")

    return claude


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    """Test YAML frontmatter parsing."""

    def test_parse_valid_frontmatter(self):
        """Standard frontmatter with multiple keys is parsed."""
        content = "---\nname: Eva\ndescription: An AI agent\nmodel: opus\n---\nBody text here."
        fm, body = parse_frontmatter(content)
        assert fm["name"] == "Eva"
        assert fm["description"] == "An AI agent"
        assert fm["model"] == "opus"
        assert body.strip() == "Body text here."

    def test_parse_no_frontmatter(self):
        """Content without frontmatter returns empty dict and full content."""
        content = "Just a body with no frontmatter."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_parse_incomplete_frontmatter(self):
        """Content with only one --- delimiter returns empty dict and full content."""
        content = "---\nname: Eva\nSome body"
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_parse_empty_frontmatter(self):
        """Empty frontmatter block returns empty dict."""
        content = "---\n---\nBody only."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body.strip() == "Body only."

    def test_parse_value_with_colon(self):
        """Values containing colons are preserved (split on first colon only)."""
        content = "---\nurl: http://example.com:8080\n---\nBody."
        fm, body = parse_frontmatter(content)
        assert fm["url"] == "http://example.com:8080"


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    """Test AgentConfig dataclass and methods."""

    def test_from_file(self, claude_dir):
        """AgentConfig.from_file parses a markdown agent file."""
        agents_dir = claude_dir / "agents"
        filepath = _write_agent(
            agents_dir,
            "eva.md",
            name="Eva",
            description="Senior dev agent",
            model="opus",
            color="purple",
            body="You are Eva.",
        )
        agent = AgentConfig.from_file(filepath)
        assert agent.filename == "eva.md"
        assert agent.name == "Eva"
        assert agent.description == "Senior dev agent"
        assert agent.model == "opus"
        assert agent.color == "purple"
        assert agent.body == "You are Eva."

    def test_from_file_defaults(self, claude_dir):
        """Missing frontmatter keys fall back to defaults."""
        agents_dir = claude_dir / "agents"
        filepath = agents_dir / "minimal.md"
        filepath.write_text("---\n---\nJust a body.")
        agent = AgentConfig.from_file(filepath)
        assert agent.name == "minimal"  # stem of filename
        assert agent.description == ""
        assert agent.model == "sonnet"
        assert agent.color == "green"

    def test_to_markdown(self):
        """to_markdown produces valid markdown with frontmatter."""
        agent = AgentConfig(
            filename="test.md",
            name="Test",
            description="A test",
            model="haiku",
            color="red",
            body="Test body.",
        )
        md = agent.to_markdown()
        assert md.startswith("---")
        assert "name: Test" in md
        assert "description: A test" in md
        assert "model: haiku" in md
        assert "color: red" in md
        assert "Test body." in md

    def test_roundtrip(self, claude_dir):
        """An agent can be written and read back identically."""
        agents_dir = claude_dir / "agents"
        agent = AgentConfig(
            filename="roundtrip.md",
            name="Roundtrip",
            description="Testing roundtrip",
            model="sonnet",
            color="blue",
            body="Roundtrip body.",
        )
        filepath = agents_dir / agent.filename
        filepath.write_text(agent.to_markdown())
        loaded = AgentConfig.from_file(filepath)
        assert loaded.name == agent.name
        assert loaded.description == agent.description
        assert loaded.model == agent.model
        assert loaded.color == agent.color
        assert loaded.body == agent.body


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    """Test list_agents function."""

    def test_list_agents_with_files(self, claude_dir):
        """Returns AgentConfig objects for each .md file in agents dir."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "alpha.md", name="Alpha")
        _write_agent(agents_dir, "beta.md", name="Beta")

        agents = list_agents()
        assert len(agents) == 2
        names = [a.name for a in agents]
        assert "Alpha" in names
        assert "Beta" in names

    def test_list_agents_sorted(self, claude_dir):
        """Agents are returned sorted by filename."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "zeta.md", name="Zeta")
        _write_agent(agents_dir, "alpha.md", name="Alpha")

        agents = list_agents()
        assert agents[0].filename == "alpha.md"
        assert agents[1].filename == "zeta.md"

    def test_list_agents_empty_directory(self, claude_dir):
        """Empty agents directory returns empty list."""
        agents = list_agents()
        assert agents == []

    def test_list_agents_no_directory(self, claude_dir, monkeypatch):
        """Non-existent agents directory returns empty list."""
        monkeypatch.setattr(config_manager, "AGENTS_DIR", claude_dir / "nonexistent")
        agents = list_agents()
        assert agents == []

    def test_list_agents_skips_malformed_files(self, claude_dir):
        """Malformed agent files are skipped with a warning."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "good.md", name="Good")
        # Create a file that will cause an error when read (binary content that breaks parsing)
        bad_file = agents_dir / "bad.md"
        bad_file.write_bytes(b"\x80\x81\x82")  # Invalid UTF-8

        agents = list_agents()
        assert len(agents) == 1
        assert agents[0].name == "Good"

    def test_list_agents_ignores_non_md_files(self, claude_dir):
        """Non-.md files in agents directory are ignored."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "agent.md", name="Agent")
        (agents_dir / "readme.txt").write_text("Not an agent")

        agents = list_agents()
        assert len(agents) == 1
        assert agents[0].name == "Agent"


# ---------------------------------------------------------------------------
# load_agent / save_agent / delete_agent
# ---------------------------------------------------------------------------


class TestAgentCrud:
    """Test agent CRUD operations."""

    def test_load_agent_exists(self, claude_dir):
        """Loading an existing agent returns AgentConfig."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "eva.md", name="Eva")
        agent = load_agent("eva.md")
        assert agent is not None
        assert agent.name == "Eva"

    def test_load_agent_not_found(self, claude_dir):
        """Loading a non-existent agent returns None."""
        agent = load_agent("nonexistent.md")
        assert agent is None

    def test_save_agent(self, claude_dir):
        """Saving an agent writes the file to disk."""
        agent = AgentConfig(
            filename="new.md",
            name="New Agent",
            description="Freshly created",
            body="Agent body.",
        )
        save_agent(agent)
        filepath = claude_dir / "agents" / "new.md"
        assert filepath.exists()
        content = filepath.read_text()
        assert "name: New Agent" in content

    def test_delete_agent_exists(self, claude_dir):
        """Deleting an existing agent returns True and removes file."""
        agents_dir = claude_dir / "agents"
        _write_agent(agents_dir, "doomed.md", name="Doomed")
        assert delete_agent("doomed.md") is True
        assert not (agents_dir / "doomed.md").exists()

    def test_delete_agent_not_found(self, claude_dir):
        """Deleting a non-existent agent returns False."""
        assert delete_agent("ghost.md") is False


# ---------------------------------------------------------------------------
# CommandConfig
# ---------------------------------------------------------------------------


class TestCommandConfig:
    """Test CommandConfig dataclass and methods."""

    def test_from_file(self, claude_dir):
        """CommandConfig.from_file parses a command markdown file."""
        commands_dir = claude_dir / "commands"
        filepath = _write_command(
            commands_dir,
            "deploy.md",
            description="Deploy to production",
            body="Run deployment script.",
        )
        cmd = CommandConfig.from_file(filepath)
        assert cmd.filename == "deploy.md"
        assert cmd.description == "Deploy to production"
        assert cmd.body == "Run deployment script."

    def test_to_markdown(self):
        """to_markdown produces valid markdown with frontmatter."""
        cmd = CommandConfig(
            filename="test.md",
            description="Test command",
            body="Test body.",
        )
        md = cmd.to_markdown()
        assert "description: Test command" in md
        assert "Test body." in md


# ---------------------------------------------------------------------------
# list_commands
# ---------------------------------------------------------------------------


class TestListCommands:
    """Test list_commands function."""

    def test_list_commands_with_files(self, claude_dir):
        """Returns CommandConfig objects for each .md file in commands dir."""
        commands_dir = claude_dir / "commands"
        _write_command(commands_dir, "build.md", description="Build project")
        _write_command(commands_dir, "test.md", description="Run tests")

        commands = list_commands()
        assert len(commands) == 2
        descs = [c.description for c in commands]
        assert "Build project" in descs
        assert "Run tests" in descs

    def test_list_commands_sorted(self, claude_dir):
        """Commands are returned sorted by filename."""
        commands_dir = claude_dir / "commands"
        _write_command(commands_dir, "zebra.md", description="Z command")
        _write_command(commands_dir, "alpha.md", description="A command")

        commands = list_commands()
        assert commands[0].filename == "alpha.md"
        assert commands[1].filename == "zebra.md"

    def test_list_commands_empty_directory(self, claude_dir):
        """Empty commands directory returns empty list."""
        commands = list_commands()
        assert commands == []

    def test_list_commands_no_directory(self, claude_dir, monkeypatch):
        """Non-existent commands directory returns empty list."""
        monkeypatch.setattr(config_manager, "COMMANDS_DIR", claude_dir / "nonexistent")
        commands = list_commands()
        assert commands == []

    def test_list_commands_skips_malformed(self, claude_dir):
        """Malformed command files are skipped."""
        commands_dir = claude_dir / "commands"
        _write_command(commands_dir, "good.md", description="Good")
        bad_file = commands_dir / "bad.md"
        bad_file.write_bytes(b"\x80\x81\x82")

        commands = list_commands()
        assert len(commands) == 1
        assert commands[0].description == "Good"


# ---------------------------------------------------------------------------
# load_command / save_command / delete_command
# ---------------------------------------------------------------------------


class TestCommandCrud:
    """Test command CRUD operations."""

    def test_load_command_exists(self, claude_dir):
        """Loading an existing command returns CommandConfig."""
        commands_dir = claude_dir / "commands"
        _write_command(commands_dir, "lint.md", description="Run linter")
        cmd = load_command("lint.md")
        assert cmd is not None
        assert cmd.description == "Run linter"

    def test_load_command_not_found(self, claude_dir):
        """Loading a non-existent command returns None."""
        cmd = load_command("nonexistent.md")
        assert cmd is None

    def test_save_command(self, claude_dir):
        """Saving a command writes the file to disk."""
        cmd = CommandConfig(
            filename="new-cmd.md",
            description="New command",
            body="Do new things.",
        )
        save_command(cmd)
        filepath = claude_dir / "commands" / "new-cmd.md"
        assert filepath.exists()
        content = filepath.read_text()
        assert "description: New command" in content

    def test_delete_command_exists(self, claude_dir):
        """Deleting an existing command returns True and removes file."""
        commands_dir = claude_dir / "commands"
        _write_command(commands_dir, "doomed.md", description="Doomed")
        assert delete_command("doomed.md") is True
        assert not (commands_dir / "doomed.md").exists()

    def test_delete_command_not_found(self, claude_dir):
        """Deleting a non-existent command returns False."""
        assert delete_command("ghost.md") is False


# ---------------------------------------------------------------------------
# Settings (load / save)
# ---------------------------------------------------------------------------


class TestSettings:
    """Test load_settings and save_settings."""

    def test_load_settings_exists(self, claude_dir):
        """load_settings reads existing settings.json."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {"key": "value"})
        result = load_settings()
        assert result == {"key": "value"}

    def test_load_settings_not_found(self, claude_dir):
        """load_settings returns empty dict when file does not exist."""
        result = load_settings()
        assert result == {}

    def test_save_settings(self, claude_dir):
        """save_settings writes JSON with 2-space indent."""
        save_settings({"test": True})
        settings_file = claude_dir / "settings.json"
        assert settings_file.exists()
        content = settings_file.read_text()
        assert '"test": true' in content
        # Check 2-space indentation
        parsed = json.loads(content)
        assert parsed == {"test": True}

    def test_save_settings_creates_parent_dirs(self, claude_dir, monkeypatch):
        """save_settings creates parent directories if they don't exist."""
        deep_path = claude_dir / "deep" / "nested" / "settings.json"
        monkeypatch.setattr(config_manager, "SETTINGS_FILE", deep_path)
        save_settings({"nested": True})
        assert deep_path.exists()


# ---------------------------------------------------------------------------
# list_hooks
# ---------------------------------------------------------------------------


class TestListHooks:
    """Test list_hooks function."""

    def test_list_hooks_with_hooks(self, claude_dir):
        """Returns HookConfig objects from settings.json hooks section."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo 'prompt submitted'",
                                    "timeout": 10,
                                }
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo 'stopped'",
                                    "timeout": 5,
                                }
                            ]
                        }
                    ],
                }
            },
        )
        hooks = list_hooks()
        assert len(hooks) == 2
        events = [h.event for h in hooks]
        assert "UserPromptSubmit" in events
        assert "Stop" in events

    def test_list_hooks_multiple_in_same_event(self, claude_dir):
        """Multiple hooks under the same event are all returned."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"type": "command", "command": "lint", "timeout": 10},
                                {"type": "command", "command": "typecheck", "timeout": 20},
                            ]
                        }
                    ]
                }
            },
        )
        hooks = list_hooks()
        assert len(hooks) == 2
        commands = [h.command for h in hooks]
        assert "lint" in commands
        assert "typecheck" in commands

    def test_list_hooks_empty_settings(self, claude_dir):
        """No settings file means no hooks."""
        hooks = list_hooks()
        assert hooks == []

    def test_list_hooks_no_hooks_key(self, claude_dir):
        """Settings without hooks key returns empty list."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {"other": "stuff"})
        hooks = list_hooks()
        assert hooks == []

    def test_list_hooks_defaults(self, claude_dir):
        """Hook with missing timeout and type gets defaults."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {"hooks": {"Stop": [{"hooks": [{"command": "cleanup"}]}]}})
        hooks = list_hooks()
        assert len(hooks) == 1
        assert hooks[0].timeout == 30  # default
        assert hooks[0].hook_type == "command"  # default
        assert hooks[0].command == "cleanup"
        assert hooks[0].event == "Stop"


# ---------------------------------------------------------------------------
# save_hook / delete_hook
# ---------------------------------------------------------------------------


class TestHookCrud:
    """Test hook save and delete operations."""

    def test_save_hook_new(self, claude_dir):
        """Saving a new hook adds it to settings."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {})

        hook = HookConfig(event="Stop", command="echo bye", timeout=15)
        save_hook(hook)

        settings = load_settings()
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]
        hook_data = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook_data["command"] == "echo bye"
        assert hook_data["timeout"] == 15

    def test_save_hook_update_existing(self, claude_dir):
        """Saving a hook with same command updates the existing one."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "cleanup", "timeout": 10}]}]
                }
            },
        )

        hook = HookConfig(event="Stop", command="cleanup", timeout=60)
        save_hook(hook)

        settings = load_settings()
        hook_data = settings["hooks"]["Stop"][0]["hooks"][0]
        assert hook_data["command"] == "cleanup"
        assert hook_data["timeout"] == 60

    def test_delete_hook_exists(self, claude_dir):
        """Deleting an existing hook returns True."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "cleanup", "timeout": 10}]}]
                }
            },
        )
        assert delete_hook("Stop", "cleanup") is True
        # Verify the hook is removed from settings
        settings = load_settings()
        remaining = settings["hooks"]["Stop"][0]["hooks"]
        assert len(remaining) == 0

    def test_delete_hook_wrong_event(self, claude_dir):
        """Deleting a hook from a non-existent event returns False."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {"hooks": {}})
        assert delete_hook("NonExistent", "cleanup") is False

    def test_delete_hook_wrong_command(self, claude_dir):
        """Deleting a hook with non-matching command returns False."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "cleanup", "timeout": 10}]}]
                }
            },
        )
        assert delete_hook("Stop", "nonexistent") is False


# ---------------------------------------------------------------------------
# PluginInfo
# ---------------------------------------------------------------------------


class TestPluginInfo:
    """Test PluginInfo dataclass."""

    def test_display_name_with_at(self):
        """display_name extracts the part before @."""
        plugin = PluginInfo(name="context7@claude-plugins-official", version="1.0", enabled=True)
        assert plugin.display_name == "context7"

    def test_display_name_without_at(self):
        """display_name returns full name if no @ present."""
        plugin = PluginInfo(name="simple-plugin", version="1.0", enabled=False)
        assert plugin.display_name == "simple-plugin"


# ---------------------------------------------------------------------------
# list_plugins / set_plugin_enabled
# ---------------------------------------------------------------------------


class TestPlugins:
    """Test plugin listing and management."""

    def test_list_plugins_from_installed_file(self, claude_dir):
        """Plugins are loaded from installed_plugins.json with enabled state from settings."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "enabledPlugins": {
                    "tool@vendor": True,
                    "other@vendor": False,
                }
            },
        )
        plugins_file = claude_dir / "plugins" / "installed_plugins.json"
        plugins_file.write_text(
            json.dumps(
                {
                    "plugins": {
                        "tool@vendor": [{"version": "2.0", "installedAt": "2025-01-01"}],
                        "other@vendor": [{"version": "1.0", "installedAt": "2025-01-02"}],
                    }
                }
            )
        )

        plugins = list_plugins()
        assert len(plugins) == 2
        by_name = {p.name: p for p in plugins}
        assert by_name["tool@vendor"].enabled is True
        assert by_name["tool@vendor"].version == "2.0"
        assert by_name["other@vendor"].enabled is False

    def test_list_plugins_fallback_settings_only(self, claude_dir):
        """When installed_plugins.json doesn't exist, fall back to settings."""
        settings_file = claude_dir / "settings.json"
        _write_settings(
            settings_file,
            {
                "enabledPlugins": {
                    "fallback@vendor": True,
                }
            },
        )
        # No installed_plugins.json file

        plugins = list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "fallback@vendor"
        assert plugins[0].enabled is True
        assert plugins[0].version == ""

    def test_list_plugins_empty(self, claude_dir):
        """No settings and no plugins file returns empty list."""
        plugins = list_plugins()
        assert plugins == []

    def test_set_plugin_enabled(self, claude_dir):
        """set_plugin_enabled updates the settings file."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {})

        set_plugin_enabled("my-plugin@vendor", True)
        settings = load_settings()
        assert settings["enabledPlugins"]["my-plugin@vendor"] is True

    def test_set_plugin_disabled(self, claude_dir):
        """set_plugin_enabled can disable a plugin."""
        settings_file = claude_dir / "settings.json"
        _write_settings(settings_file, {"enabledPlugins": {"my-plugin@vendor": True}})

        set_plugin_enabled("my-plugin@vendor", False)
        settings = load_settings()
        assert settings["enabledPlugins"]["my-plugin@vendor"] is False

# Contributing to Synthia

First off, thanks for considering contributing to Synthia! It's people like you that make Synthia a great tool for everyone.

## Ways to Contribute

### Reporting Bugs
- Check existing issues first to avoid duplicates
- Use the bug report template
- Include your system info (OS, Python version, GPU)
- Provide steps to reproduce

### Suggesting Features
- Open an issue with the `enhancement` label
- Describe the use case, not just the solution
- Check the [ROADMAP.md](ROADMAP.md) to see if it's already planned

### Code Contributions
We welcome PRs! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly
5. Commit with clear messages (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

### Prerequisites
- Python 3.10+
- Linux with X11 (for now - cross-platform coming!)
- NVIDIA GPU (optional, for faster inference)

### Getting Started

```bash
# Clone your fork
git clone https://github.com/YOUR-USERNAME/synthia.git
cd synthia

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install pytest black isort mypy

# Install system dependencies
sudo apt install xdotool portaudio19-dev mpv xclip wmctrl alsa-utils

# Install Ollama for local LLM
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct-q4_0
```

### Running Tests

```bash
pytest tests/
```

### Code Style

We use:
- **Black** for formatting
- **isort** for import sorting
- **mypy** for type checking

```bash
# Format code
black .
isort .

# Type check
mypy --ignore-missing-imports .
```

## Project Structure

```
synthia/
├── main.py              # Entry point
├── assistant.py         # LLM integration (Ollama/Claude)
├── audio.py             # Audio recording
├── transcribe.py        # Speech-to-text (Whisper)
├── tts.py               # Text-to-speech (Piper)
├── commands.py          # Voice command handlers
├── config.py            # Configuration management
├── claude-hooks/        # Claude Code integration
│   └── stop-hook.py     # Hook for Claude responses
├── remote/              # Telegram remote control
│   ├── telegram_bot.py  # Bot implementation
│   └── send_telegram.py # Helper for sending messages
└── tests/               # Test suite
```

## Key Areas for Contribution

### High Impact
- **Cross-platform support** - Help bring Synthia to macOS and Windows
- **New voice commands** - Add useful commands to `commands.py`
- **GUI development** - Help build the Rust GUI (Phase 4)

### Good First Issues
Look for issues labeled `good first issue` - these are great starting points:
- Documentation improvements
- Bug fixes with clear reproduction steps
- Small feature additions

### Advanced
- Wayland support
- Mobile app development
- Plugin system architecture

## Code Guidelines

1. **Keep it simple** - Readable code over clever code
2. **Document public functions** - Docstrings for anything public
3. **Test your changes** - Add tests for new functionality
4. **Small PRs** - Easier to review and merge

## Questions?

- Open a Discussion for general questions
- Tag maintainers if you're stuck on a PR

Thanks for helping make Synthia better!

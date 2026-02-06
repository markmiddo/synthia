#!/bin/bash
# ============================================================================
# Synthia Installation Script
# Version: 0.1.0
#
# This script sets up Synthia - a voice-controlled Claude Code companion
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}"
echo "  ____  _   _ _   _ _____ _   _ ___    _    "
echo " / ___|| | | | \ | |_   _| | | |_ _|  / \   "
echo " \___ \| |_| |  \| | | | | |_| || |  / _ \  "
echo "  ___) |  _  | |\  | | | |  _  || | / ___ \ "
echo " |____/|_| |_|_| \_| |_| |_| |_|___/_/   \_\\"
echo -e "${NC}"
echo -e "${BLUE}Voice-Controlled Claude Code Companion${NC}"
echo ""

# ============================================================================
# Check system requirements
# ============================================================================
echo -e "${BLUE}Checking system requirements...${NC}"

# Check OS
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo -e "${RED}Error: Synthia currently only supports Linux.${NC}"
    echo "macOS and Windows support coming in v0.3"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Linux detected"

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    echo "Install Python 3.10+ and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo -e "${RED}Error: Python 3.10+ is required. Found: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION"

# Check for pip
if ! python3 -m pip --version &> /dev/null; then
    echo -e "${RED}Error: pip is required but not installed.${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} pip available"

# Check for PortAudio (required for PyAudio)
if ! pkg-config --exists portaudio-2.0 2>/dev/null; then
    echo -e "${YELLOW}Warning: PortAudio not found. PyAudio may fail to install.${NC}"
    echo -e "  Install with: ${CYAN}sudo apt install portaudio19-dev${NC} (Debian/Ubuntu)"
    echo -e "  Or: ${CYAN}sudo pacman -S portaudio${NC} (Arch)"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "  ${GREEN}✓${NC} PortAudio"
fi

echo ""

# ============================================================================
# Create Python virtual environment
# ============================================================================
echo -e "${BLUE}Setting up Python environment...${NC}"

if [ -d "$SCRIPT_DIR/venv" ]; then
    echo -e "  ${YELLOW}Existing venv found. Removing...${NC}"
    rm -rf "$SCRIPT_DIR/venv"
fi

python3 -m venv "$SCRIPT_DIR/venv"
source "$SCRIPT_DIR/venv/bin/activate"
pip install --upgrade pip wheel setuptools -q
echo -e "  ${GREEN}✓${NC} Virtual environment created"

# ============================================================================
# Install Synthia package
# ============================================================================
echo -e "${BLUE}Installing Synthia...${NC}"
pip install -e "$SCRIPT_DIR" -q
echo -e "  ${GREEN}✓${NC} Synthia package installed"

# ============================================================================
# Download Whisper model (for speech recognition)
# ============================================================================
echo -e "${BLUE}Downloading speech recognition model...${NC}"
echo -e "  This may take a moment on first run..."
python3 -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')" 2>/dev/null || true
echo -e "  ${GREEN}✓${NC} Whisper model ready"

# ============================================================================
# Download Piper voice (for text-to-speech)
# ============================================================================
echo -e "${BLUE}Downloading voice model...${NC}"
VOICE_DIR="$HOME/.local/share/piper-voices"
mkdir -p "$VOICE_DIR"

if [ ! -f "$VOICE_DIR/en_US-amy-medium.onnx" ]; then
    echo -e "  Downloading Amy voice (~60MB)..."
    curl -sL -o "$VOICE_DIR/en_US-amy-medium.onnx" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
    curl -sL -o "$VOICE_DIR/en_US-amy-medium.onnx.json" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
    echo -e "  ${GREEN}✓${NC} Voice model downloaded"
else
    echo -e "  ${GREEN}✓${NC} Voice model already exists"
fi

# ============================================================================
# Check for Ollama (for local LLM in Quick Mode)
# ============================================================================
echo -e "${BLUE}Checking Ollama installation...${NC}"
if command -v ollama &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Ollama found"

    # Check if qwen model is installed
    if ollama list 2>/dev/null | grep -q "qwen2.5:1.5b-instruct"; then
        echo -e "  ${GREEN}✓${NC} Qwen model available"
    else
        echo -e "  ${YELLOW}Qwen model not found. Pulling...${NC}"
        echo -e "  This may take a few minutes (~1GB download)..."
        ollama pull qwen2.5:1.5b-instruct-q4_0 || echo -e "  ${YELLOW}Warning: Could not pull model. Quick Mode may not work.${NC}"
    fi
else
    echo -e "  ${YELLOW}Ollama not found.${NC}"
    echo -e "  Quick Mode requires Ollama. Install from: ${CYAN}https://ollama.ai${NC}"
    echo -e "  Then run: ${CYAN}ollama pull qwen2.5:1.5b-instruct-q4_0${NC}"
fi

# ============================================================================
# Create config file
# ============================================================================
echo -e "${BLUE}Setting up configuration...${NC}"
CONFIG_DIR="$HOME/.config/synthia"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cat > "$CONFIG_DIR/config.yaml" << 'EOF'
# Synthia Configuration

# Hotkeys
dictation_key: "Key.ctrl_r"      # Hold for Dev Mode (Claude Code)
assistant_key: "Key.alt_r"       # Hold for Quick Mode (local AI)

# Speech Recognition - LOCAL
use_local_stt: true
local_stt_model: "tiny"          # tiny, base, small, medium, large
language: "en-US"
sample_rate: 16000

# Local LLM for Quick Mode
use_local_llm: true
local_llm_model: "qwen2.5:1.5b-instruct-q4_0"

# Text-to-Speech - LOCAL
use_local_tts: true
local_tts_voice: "~/.local/share/piper-voices/en_US-amy-medium.onnx"
tts_speed: 1.0

# Memory System
memory_enabled: true
memory_auto_retrieve: false
memory_dir: "~/.claude/memory"

# Claude Code Integration
claude_hooks_enabled: true

# UI
show_notifications: true
play_sound_on_record: true

# Word replacements for dictation
word_replacements:
  Cynthia: Synthia
  cynthia: synthia
EOF
    echo -e "  ${GREEN}✓${NC} Config created at $CONFIG_DIR/config.yaml"
else
    echo -e "  ${GREEN}✓${NC} Config already exists"
fi

# ============================================================================
# Create symlinks in ~/.local/bin
# ============================================================================
echo -e "${BLUE}Creating command shortcuts...${NC}"
mkdir -p "$HOME/.local/bin"

ln -sf "$SCRIPT_DIR/venv/bin/synthia" "$HOME/.local/bin/synthia"
ln -sf "$SCRIPT_DIR/venv/bin/synthia-dash" "$HOME/.local/bin/synthia-dash"
echo -e "  ${GREEN}✓${NC} Commands linked to ~/.local/bin"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "  ${YELLOW}Note: ~/.local/bin is not in your PATH${NC}"

    # Add to appropriate shell config
    SHELL_CONFIG=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_CONFIG="$HOME/.bashrc"
    fi

    if [ -n "$SHELL_CONFIG" ]; then
        if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$SHELL_CONFIG" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
            echo -e "  ${GREEN}✓${NC} Added to $SHELL_CONFIG"
        fi
    fi
fi

# ============================================================================
# GUI Build (optional)
# ============================================================================
echo ""
echo -e "${BLUE}GUI Installation${NC}"
echo -e "The desktop GUI requires Rust and takes ~3 minutes to build."
read -p "Would you like to build the GUI now? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check for Rust
    if ! command -v cargo &> /dev/null; then
        echo -e "  ${YELLOW}Rust not found. Installing...${NC}"
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    # Check for npm
    if ! command -v npm &> /dev/null; then
        echo -e "  ${RED}npm not found. Please install Node.js and try again.${NC}"
    else
        echo -e "  ${BLUE}Building GUI (this takes a few minutes)...${NC}"
        cd "$SCRIPT_DIR/gui"
        npm install -q
        npm run tauri build 2>&1 | tail -5

        if [ -f "$SCRIPT_DIR/gui/src-tauri/target/release/synthia-gui" ]; then
            ln -sf "$SCRIPT_DIR/gui/src-tauri/target/release/synthia-gui" "$HOME/.local/bin/synthia-gui"
            echo -e "  ${GREEN}✓${NC} GUI built and linked"
        fi
    fi
fi

# ============================================================================
# Claude Code Integration (optional)
# ============================================================================
echo ""
echo -e "${BLUE}Claude Code Integration${NC}"
echo -e "Add a hook so Claude speaks responses aloud?"
read -p "(y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    CLAUDE_SETTINGS="$HOME/.claude/settings.json"

    if [ -f "$CLAUDE_SETTINGS" ]; then
        # Check if hook already exists
        if grep -q "stop-hook.py" "$CLAUDE_SETTINGS" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Hook already configured"
        else
            echo -e "  ${YELLOW}Please add this to your ~/.claude/settings.json hooks:${NC}"
            echo ""
            echo -e "${CYAN}\"Stop\": [{
  \"hooks\": [{
    \"type\": \"command\",
    \"command\": \"$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/src/synthia/hooks/stop-hook.py\",
    \"timeout\": 30
  }]
}]${NC}"
            echo ""
        fi
    else
        echo -e "  ${YELLOW}Claude Code settings not found.${NC}"
        echo -e "  Run Claude Code once, then re-run this script to configure hooks."
    fi
fi

# ============================================================================
# Done!
# ============================================================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Installation Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Available commands:"
echo -e "  ${CYAN}synthia${NC}       - Start voice assistant"
echo -e "  ${CYAN}synthia-dash${NC}  - Open TUI dashboard"
if [ -f "$HOME/.local/bin/synthia-gui" ]; then
echo -e "  ${CYAN}synthia-gui${NC}   - Launch desktop app"
fi
echo ""
echo -e "Hotkeys:"
echo -e "  ${CYAN}Right Alt${NC} (hold)  - Quick Mode (local AI)"
echo -e "  ${CYAN}Right Ctrl${NC} (hold) - Dev Mode (Claude Code)"
echo ""
echo -e "${YELLOW}Restart your terminal or run:${NC}"
echo -e "  source ~/.bashrc  ${CYAN}# or ~/.zshrc${NC}"
echo ""
echo -e "Then start Synthia with: ${CYAN}./run.sh${NC}"
echo ""

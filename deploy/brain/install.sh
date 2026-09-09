#!/usr/bin/env bash
# Install or update the Synthia brain on this machine (run on middo247 as markmiddo).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -e ".[dev,brain]"
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found; install with sudo apt install ffmpeg"
mkdir -p ~/.config/systemd/user ~/.config/synthia
cp deploy/brain/synthia-brain.service deploy/brain/eventflo-pull.service deploy/brain/eventflo-pull.timer ~/.config/systemd/user/
[ -f ~/.config/synthia/brain.env ] || { cp deploy/brain/brain.env.example ~/.config/synthia/brain.env; chmod 600 ~/.config/synthia/brain.env; echo "Edit ~/.config/synthia/brain.env"; }
[ -f ~/.config/synthia/brain.yaml ] || cp deploy/brain/brain.yaml.example ~/.config/synthia/brain.yaml
systemctl --user daemon-reload
systemctl --user enable --now eventflo-pull.timer
systemctl --user enable synthia-brain.service
systemctl --user restart synthia-brain.service
loginctl enable-linger "$USER" >/dev/null 2>&1 || true
echo "Done. Logs: journalctl --user -u synthia-brain -f"

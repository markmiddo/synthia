#!/usr/bin/env bash
# Install or update the Synthia brain on this machine (run on middo247 as markmiddo).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -e ".[dev,brain]"
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found; install with sudo apt install ffmpeg"
mkdir -p ~/.config/systemd/user ~/.config/synthia ~/.config/synthia/security
cp deploy/brain/synthia-brain.service deploy/brain/eventflo-pull.service deploy/brain/eventflo-pull.timer ~/.config/systemd/user/
[ -f ~/.config/synthia/brain.env ] || { cp deploy/brain/brain.env.example ~/.config/synthia/brain.env; chmod 600 ~/.config/synthia/brain.env; echo "Edit ~/.config/synthia/brain.env"; }
[ -f ~/.config/synthia/brain.yaml ] || cp deploy/brain/brain.yaml.example ~/.config/synthia/brain.yaml
# Headless server policy for the synced PreToolUse security-gate hook: deny HIGH outright
# rather than stalling thirty seconds on a GUI prompt nobody can answer.
[ -f ~/.config/synthia/security/policy.yaml ] || cp deploy/brain/security-policy.yaml ~/.config/synthia/security/policy.yaml
systemctl --user daemon-reload
systemctl --user enable --now eventflo-pull.timer

if grep -q 'replace-me' ~/.config/synthia/brain.env; then
  echo
  echo "brain.env still has the placeholder token, so the service was NOT started."
  echo "  1. nano ~/.config/synthia/brain.env     # real BRAIN_TELEGRAM_TOKEN and Google credentials path"
  echo "  2. nano ~/.config/synthia/brain.yaml    # telegram_allowed_users and telegram_chat_id"
  echo "Then re-run deploy/brain/install.sh."
  exit 0
fi

systemctl --user enable synthia-brain.service
systemctl --user restart synthia-brain.service
loginctl enable-linger "$USER" >/dev/null 2>&1 || true
echo "Done. Logs: journalctl --user -u synthia-brain -f"

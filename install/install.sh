#!/usr/bin/env bash
# Install the `jade` command + systemd user service.
#
# Run from anywhere:
#   bash install/install.sh
#
# Safe to re-run. Doesn't touch root. Files installed under your home:
#   ~/.local/bin/jade
#   ~/.config/systemd/user/jade.service

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 1. Install wrapper script.
mkdir -p "$HOME/.local/bin"
install -m 0755 "$REPO_ROOT/install/jade" "$HOME/.local/bin/jade"
echo "→ ~/.local/bin/jade installed"

# Make sure ~/.local/bin is in PATH.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        echo "⚠ ~/.local/bin is not in your PATH. Add to ~/.bashrc / ~/.zshrc:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

# 2. Install systemd user unit.
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 "$REPO_ROOT/install/jade.service" "$HOME/.config/systemd/user/jade.service"
echo "→ ~/.config/systemd/user/jade.service installed"

systemctl --user daemon-reload

# 3. Tell the user how to enable.
cat <<'EOF'

Installed. Useful commands:

  jade                                # run now in this terminal (voice-only)
  jade --interactive                  # run with tk window + tray
  systemctl --user enable --now jade  # start now + auto-start at login
  systemctl --user disable --now jade # turn off auto-start + stop
  systemctl --user restart jade       # restart (after persona / config changes)
  systemctl --user status jade        # is she running?
  journalctl --user -u jade -f        # tail her logs

The service runs the voice-only headless mode and Jade will greet you out loud
when she finishes loading. Edit the service file to change which model she uses
or to pin Whisper to CPU:
  ~/.config/systemd/user/jade.service
Then: systemctl --user daemon-reload && systemctl --user restart jade

To linger across login sessions (so she keeps running when you switch users):
  loginctl enable-linger $USER
EOF

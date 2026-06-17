#!/usr/bin/env bash
# install_service.sh — Install nap-of-the-rpi as a systemd service
# Run with: sudo bash scripts/install_service.sh

set -euo pipefail

SERVICE_NAME="nap-of-the-rpi"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER="${SUDO_USER:-pi}"
UV_PATH="$(which uv || echo '/home/'"$USER"'/.local/bin/uv')"

echo "Installing systemd service: $SERVICE_NAME"
echo "  Project dir: $PROJECT_DIR"
echo "  User: $USER"
echo "  uv path: $UV_PATH"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=nap-of-the-rpi: PIR detection, laser, weather TTS
After=bluetooth.target network-online.target
Wants=network-online.target

[Service]
Type=notify
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$UV_PATH run python main.py
Restart=always
RestartSec=5
StartLimitIntervalSec=120
StartLimitBurst=5
WatchdogSec=30
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/home/$USER/.local/bin

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "Service installed and enabled."
echo "  Start:   sudo systemctl start $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    journalctl -u $SERVICE_NAME -f"

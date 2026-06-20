#!/usr/bin/env bash
# install_service.sh — Install nap-of-the-rpi as a systemd service
#
# This script:
# 1. Generates a systemd unit file
# 2. Installs it to /etc/systemd/system/
# 3. Enables it (auto-start on boot)
# 4. Optionally starts it immediately
#
# Usage:
#   sudo bash scripts/install_service.sh
#
# The service will:
# - Run as the 'pi' user (not root — safer)
# - Auto-restart on failure (up to 5 times in 2 minutes)
# - Use systemd watchdog (restart if app hangs for 30s)
# - Wait for Bluetooth and network before starting
# - Log to journald (use: journalctl -u nap-of-the-rpi -f)

set -euo pipefail

# ----------------------------------------------------------------------------------------------------
# Configuration
SERVICE_NAME="nap-of-the-rpi"
SERVICE_USER="${SUDO_USER:-pi}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV_BIN="$(which uv 2>/dev/null || echo "/home/${SERVICE_USER}/.local/bin/uv")"

# ----------------------------------------------------------------------------------------------------
# Check prerequisites
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

if [ ! -f "${PROJECT_DIR}/main.py" ]; then
    echo "ERROR: main.py not found in ${PROJECT_DIR}"
    exit 1
fi

echo "=== Installing ${SERVICE_NAME} systemd service ==="
echo "Project dir: ${PROJECT_DIR}"
echo "Run as user: ${SERVICE_USER}"
echo "uv binary:   ${UV_BIN}"
echo ""

# ----------------------------------------------------------------------------------------------------
# Generate systemd unit file
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "${UNIT_FILE}" << EOF
[Unit]
Description=nap-of-the-rpi: Human detection, laser, and weather TTS
Documentation=https://github.com/nap-of-the-earth/nap-of-the-rpi
After=bluetooth.target network-online.target
Wants=bluetooth.target network-online.target

[Service]
Type=notify
NotifyAccess=all

# Run as non-root user
User=${SERVICE_USER}
Group=${SERVICE_USER}

# Working directory (where config.yaml lives)
WorkingDirectory=${PROJECT_DIR}

# Start command: use uv to run within the project's venv
ExecStart=${UV_BIN} run python main.py

# Watchdog: if the app doesn't notify within 30s, assume it's hung
WatchdogSec=30

# Restart policy: always restart on failure
Restart=on-failure
RestartSec=5

# Rate limiting: max 5 restarts in 2 minutes, then give up
StartLimitIntervalSec=120
StartLimitBurst=5

# Environment (inherit user's PATH for uv/python)
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/${SERVICE_USER}/.local/bin

# Logging (goes to journald by default)
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

echo "Created: ${UNIT_FILE}"

# ----------------------------------------------------------------------------------------------------
# Reload systemd and enable service
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo ""
echo "=== Done! ==="
echo ""
echo "Commands:"
echo "  sudo systemctl start ${SERVICE_NAME}     # Start now"
echo "  sudo systemctl stop ${SERVICE_NAME}      # Stop"
echo "  sudo systemctl status ${SERVICE_NAME}    # Check status"
echo "  journalctl -u ${SERVICE_NAME} -f         # View logs (live)"
echo ""

# Ask if user wants to start now
read -p "Start the service now? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl start "${SERVICE_NAME}"
    echo "Service started!"
    systemctl status "${SERVICE_NAME}" --no-pager
fi

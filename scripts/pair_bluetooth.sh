#!/usr/bin/env bash
# pair_bluetooth.sh — Pair and trust a Bluetooth speaker
# Usage: bash scripts/pair_bluetooth.sh "JBL Flip 6"

set -euo pipefail

DEVICE_NAME="${1:-JBL Flip 6}"

echo "=== Bluetooth Pairing Helper ==="
echo "Looking for device: $DEVICE_NAME"
echo ""
echo "Make sure your speaker is in pairing mode!"
echo "Scanning for 10 seconds..."

# Start scan
bluetoothctl --timeout 10 scan on 2>/dev/null || true

# Find device MAC address
MAC=$(bluetoothctl devices | grep -i "$DEVICE_NAME" | awk '{print $2}')

if [ -z "$MAC" ]; then
    echo "ERROR: Could not find '$DEVICE_NAME'"
    echo "Available devices:"
    bluetoothctl devices
    exit 1
fi

echo "Found: $DEVICE_NAME at $MAC"
echo "Pairing..."

bluetoothctl pair "$MAC"
bluetoothctl trust "$MAC"
bluetoothctl connect "$MAC"

echo ""
echo "=== Done! ==="
echo "Device '$DEVICE_NAME' ($MAC) is paired and trusted."
echo "It will auto-connect on future boots."

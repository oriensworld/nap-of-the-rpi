"""Bluetooth utility: connection helper for Bluetooth speaker."""


class BluetoothHelper:
    """Manages Bluetooth speaker connection, reconnection, and status checks."""

    def __init__(self, device_name: str):
        self.device_name = device_name

    def is_connected(self) -> bool:
        """Check if the configured Bluetooth device is connected."""
        raise NotImplementedError

    def connect(self) -> bool:
        """Attempt to connect to the configured Bluetooth device."""
        raise NotImplementedError

    def ensure_connected(self, retries: int = 3, delay: float = 2.0) -> bool:
        """Attempt connection with retries. Returns True if connected."""
        raise NotImplementedError

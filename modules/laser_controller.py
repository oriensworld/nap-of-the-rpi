"""Laser controller module: drives KY-008 laser with configurable patterns."""


class LaserController:
    """Controls laser via GPIO with solid, blink, and pulse patterns."""

    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config

    def start(self) -> None:
        """Subscribe to events and prepare laser GPIO."""
        raise NotImplementedError

    def stop(self) -> None:
        """Ensure laser is off and clean up."""
        raise NotImplementedError

    def set_pattern(self, pattern: str) -> None:
        """Change the active laser pattern (solid, blink, pulse)."""
        raise NotImplementedError

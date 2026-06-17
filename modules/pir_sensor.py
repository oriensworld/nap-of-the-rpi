"""PIR sensor module: detects nearby humans via HC-SR501 infrared sensor."""


class PIRSensor:
    """Monitors GPIO input from HC-SR501, emits detection events with cooldown."""

    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config

    def start(self) -> None:
        """Begin monitoring PIR sensor in background thread."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop monitoring and clean up GPIO."""
        raise NotImplementedError

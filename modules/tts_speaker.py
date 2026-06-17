"""TTS speaker module: neural text-to-speech via Piper with Bluetooth output."""


class TTSSpeaker:
    """Converts text to speech using Piper TTS and plays through Bluetooth speaker."""

    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config

    def start(self) -> None:
        """Subscribe to weather_ready events and initialize audio."""
        raise NotImplementedError

    def stop(self) -> None:
        """Clean up audio resources."""
        raise NotImplementedError

    def speak(self, text: str) -> None:
        """Synthesize and play speech for the given text."""
        raise NotImplementedError

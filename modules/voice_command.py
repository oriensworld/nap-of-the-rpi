"""Voice command module: wake word detection and command parsing via Vosk."""


class VoiceCommand:
    """Listens for wake word + commands via USB microphone using Vosk offline STT."""

    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config

    def start(self) -> None:
        """Begin continuous listening in background thread."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop listening and close audio stream."""
        raise NotImplementedError

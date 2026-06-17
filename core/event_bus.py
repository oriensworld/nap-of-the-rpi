"""Event bus: lightweight pub/sub for inter-module communication."""


class EventBus:
    """Thread-safe publish/subscribe event system."""

    def subscribe(self, event_name: str, callback) -> None:
        """Register a callback for an event."""
        raise NotImplementedError

    def emit(self, event_name: str, data: dict | None = None) -> None:
        """Emit an event to all subscribers."""
        raise NotImplementedError

    def unsubscribe(self, event_name: str, callback) -> None:
        """Remove a callback from an event."""
        raise NotImplementedError

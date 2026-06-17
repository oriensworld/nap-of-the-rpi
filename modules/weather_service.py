"""Weather service module: fetches weather data from OpenWeatherMap API."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class WeatherData:
    """Parsed weather information from API response."""

    temperature: float
    condition: str
    humidity: int
    wind_speed: float
    location: str
    timestamp: datetime


class WeatherService:
    """Fetches and formats weather data, emits weather_ready events."""

    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config

    def start(self) -> None:
        """Subscribe to detection and command events."""
        raise NotImplementedError

    def stop(self) -> None:
        """Clean up resources."""
        pass

    def fetch_weather(self) -> WeatherData:
        """Fetch current weather from OpenWeatherMap API."""
        raise NotImplementedError

    def format_announcement(self, data: WeatherData) -> str:
        """Format weather data into a spoken announcement string."""
        raise NotImplementedError

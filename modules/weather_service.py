# ----------------------------------------------------------------------------------------------------
# weather_service.py
# ----------------------------------------------------------------------------------------------------

"""
Weather service module: fetches weather data from OpenWeatherMap API.

This module:
1. Subscribes to 'human_detected' and 'command_weather' events
2. Fetches current weather from OpenWeatherMap's free API
3. Formats the data into a human-readable announcement
4. Emits 'weather_ready' with the announcement text (for TTS to speak)
5. Respects cooldown to avoid repeated API calls on rapid triggers

OpenWeatherMap API:
- Free tier: 1000 calls/day
- Endpoint: https://api.openweathermap.org/data/2.5/weather
- Requires an API key (sign up at openweathermap.org)
"""

# ----------------------------------------------------------------------------------------------------
from dataclasses import dataclass
from datetime import datetime

# ----------------------------------------------------------------------------------------------------
import logging
import requests
import time

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------------
# API configuration
OPENWEATHERMAP_URL = "https://api.openweathermap.org/data/2.5/weather"
GEOLOCATION_URL = "http://ip-api.com/json/?fields=lat,lon,city,status"
REQUEST_TIMEOUT = 5  # seconds

# ----------------------------------------------------------------------------------------------------
@dataclass
class WeatherData:
    """
    Parsed weather information from API response.

    Fields:
        temperature: Current temp in configured units (F or C)
        condition: Human-readable condition (e.g., "clear sky", "light rain")
        humidity: Relative humidity percentage (0-100)
        wind_speed: Wind speed in configured units (mph or m/s)
        location: City name from API response
        timestamp: When this data was fetched
    """

    temperature: float
    condition: str
    humidity: int
    wind_speed: float
    location: str
    timestamp: datetime


# ----------------------------------------------------------------------------------------------------
class WeatherService:
    """
    Fetches and formats weather data, emits weather_ready events.

    Subscribes to:
    - 'human_detected': fetch weather when someone is nearby
    - 'command_weather': fetch weather on voice command

    Emits:
    - 'weather_ready': with formatted announcement text for TTS

    Cooldown: Respects the same cooldown as PIR sensor to avoid spamming
    the API when the sensor triggers repeatedly.

    Usage:
        service = WeatherService(event_bus, config)
        service.start()
        # Events trigger automatically, or manually:
        data = service.fetch_weather()
        text = service.format_announcement(data)
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self, event_bus, config):
        """
        Initialize the weather service.

        Args:
            event_bus: The EventBus instance for subscribing/emitting events.
            config: The Config instance (uses config.weather.* and config.pir.cooldown_seconds).
        """
        self.event_bus = event_bus
        self.config = config
        self._last_fetch_time = 0.0  # Timestamp of last successful fetch
        self._running = False
        self._coords: tuple[float, float] | None = None

    # ------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """
        Subscribe to detection and command events.
        Resolves location via IP geolocation if location_mode is "auto".
        """
        if self._running:
            logger.warning("Weather service already running")
            return

        if self.config.weather.location_mode == "auto":
            self._coords = self._resolve_location()
            if self._coords is None:
                logger.warning("Geolocation failed, falling back to config location")

        self.event_bus.subscribe("human_detected", self._on_human_detected)
        self.event_bus.subscribe("command_weather", self._on_command_weather)
        self._running = True
        logger.info("Weather service started")

    # ------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """
        Unsubscribe from events.
        """
        self._running = False
        self.event_bus.unsubscribe("human_detected", self._on_human_detected)
        self.event_bus.unsubscribe("command_weather", self._on_command_weather)
        logger.info("Weather service stopped")

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    def _resolve_location(self) -> tuple[float, float] | None:
        """
        Resolve lat/lon via IP geolocation (ip-api.com). Called once at startup.
        Returns (lat, lon) on success, None on failure.
        """
        for attempt in range(2):
            try:
                response = requests.get(GEOLOCATION_URL, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "success":
                    logger.warning("Geolocation API returned non-success status")
                    return None

                lat = data["lat"]
                lon = data["lon"]
                logger.info(f"Geolocation resolved: {data.get('city', '?')} ({lat}, {lon})")
                return (lat, lon)

            except requests.Timeout:
                logger.warning(f"Geolocation timeout (attempt {attempt + 1}/2)")
            except requests.HTTPError as e:
                logger.error(f"Geolocation HTTP error: {e}")
                return None
            except requests.RequestException as e:
                logger.warning(f"Geolocation request failed (attempt {attempt + 1}/2): {e}")
            except (KeyError, TypeError) as e:
                logger.error(f"Unexpected geolocation response format: {e}")
                return None

        return None

    def fetch_weather(self) -> WeatherData | None:
        """
        Fetch current weather from OpenWeatherMap API.

        Makes an HTTP GET request with configured API key and location.
        Retries once on failure. Returns None if both attempts fail.

        Returns:
            WeatherData on success, None on failure.
        """
        api_key = self.config.weather.api_key
        location = self.config.weather.location
        units = self.config.weather.units

        if not api_key:
            logger.error("Weather API key not configured")
            return None

        params = {
            "appid": api_key,
            "units": units,
        }

        if self._coords:
            params["lat"] = self._coords[0]
            params["lon"] = self._coords[1]
        else:
            params["q"] = location

        # Try up to 2 times (initial + 1 retry)
        for attempt in range(2):
            try:
                response = requests.get(
                    OPENWEATHERMAP_URL,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()

                return WeatherData(
                    temperature=data["main"]["temp"],
                    condition=data["weather"][0]["description"],
                    humidity=data["main"]["humidity"],
                    wind_speed=data["wind"]["speed"],
                    location=data["name"],
                    timestamp=datetime.now(),
                )

            except requests.Timeout:
                logger.warning(f"Weather API timeout (attempt {attempt + 1}/2)")
            except requests.HTTPError as e:
                logger.error(f"Weather API HTTP error: {e}")
                return None  # Don't retry on HTTP errors (bad key, etc.)
            except requests.RequestException as e:
                logger.warning(f"Weather API request failed (attempt {attempt + 1}/2): {e}")
            except (KeyError, IndexError) as e:
                logger.error(f"Unexpected weather API response format: {e}")
                return None  # Don't retry on parse errors

        return None

    # ------------------------------------------------------------------------------------------------
    def format_announcement(self, data: WeatherData) -> str:
        """
        Format weather data into a spoken announcement string.

        Args:
            data: WeatherData from fetch_weather().

        Returns:
            A natural-sounding string for TTS to speak.
            Example: "In Dallas, it's 72 degrees and clear sky. Humidity is 45 percent."
        """
        # Round temperature to nearest integer for cleaner speech
        temp = round(data.temperature)
        return (
            f"In {data.location}, it's {temp} degrees and {data.condition}. "
            f"Humidity is {data.humidity} percent."
        )

    # ------------------------------------------------------------------------------------------------
    def _on_human_detected(self, data=None) -> None:
        """
        Event handler: fetch and announce weather when human detected.

        Respects cooldown — won't re-fetch if we recently announced.
        """
        if not self._running:
            return
        self._fetch_and_announce()

    # ------------------------------------------------------------------------------------------------
    def _on_command_weather(self, data=None) -> None:
        """
        Event handler: fetch and announce weather on voice command.

        Voice commands bypass cooldown (user explicitly asked for it).
        """
        if not self._running:
            return
        self._fetch_and_announce(bypass_cooldown=True)

    # ------------------------------------------------------------------------------------------------
    def _fetch_and_announce(self, bypass_cooldown: bool = False) -> None:
        """
        Internal: fetch weather and emit announcement.

        Args:
            bypass_cooldown: If True, ignore cooldown (for explicit voice commands).
        """
        now = time.time()
        cooldown = self.config.pir.cooldown_seconds

        if not bypass_cooldown:
            elapsed = now - self._last_fetch_time
            if elapsed < cooldown:
                logger.debug(
                    f"Weather fetch skipped — within cooldown "
                    f"({elapsed:.1f}s < {cooldown}s)"
                )
                return

        # Fetch weather data
        weather_data = self.fetch_weather()

        if weather_data is not None:
            announcement = self.format_announcement(weather_data)
            self._last_fetch_time = time.time()
        else:
            announcement = "Weather data is currently unavailable."

        # Emit for TTS to pick up and speak
        logger.info(f"Weather announcement: {announcement}")
        self.event_bus.emit("weather_ready", {"text": announcement})

# ----------------------------------------------------------------------------------------------------
# test_weather_service.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the weather service module.

Uses unittest.mock to mock HTTP responses from OpenWeatherMap API.
No real API calls are made during testing.

RUN WITH:
    uv run pytest tests/test_weather_service.py -v
"""

# ----------------------------------------------------------------------------------------------------
import time
from unittest.mock import MagicMock, patch

from core.event_bus import EventBus
from modules.weather_service import WeatherData, WeatherService

# ----------------------------------------------------------------------------------------------------
# Sample API response matching OpenWeatherMap's format
SAMPLE_API_RESPONSE = {
    "main": {
        "temp": 72.5,
        "humidity": 45,
    },
    "weather": [
        {"description": "clear sky", "main": "Clear"}
    ],
    "wind": {"speed": 5.2},
    "name": "New York",
}


# ----------------------------------------------------------------------------------------------------
def make_config(cooldown=10, api_key="test-key-123", location="New York,US", units="imperial"):
    """Create a mock Config for testing."""
    config = MagicMock()
    config.weather.api_key = api_key
    config.weather.location = location
    config.weather.units = units
    config.pir.cooldown_seconds = cooldown
    return config


# ----------------------------------------------------------------------------------------------------
class TestWeatherServiceBasic:
    """Basic start/stop and lifecycle tests."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.service = WeatherService(self.bus, self.config)

    def teardown_method(self):
        self.service.stop()

    # ------------------------------------------------------------------------------------------------
    def test_start_sets_running(self):
        """After start(), the service should be running."""
        self.service.start()
        assert self.service._running is True

    # ------------------------------------------------------------------------------------------------
    def test_stop_clears_running(self):
        """After stop(), the service should not be running."""
        self.service.start()
        self.service.stop()
        assert self.service._running is False

    # ------------------------------------------------------------------------------------------------
    def test_start_twice_no_error(self):
        """Calling start() twice should not crash."""
        self.service.start()
        self.service.start()
        assert self.service._running is True


# ----------------------------------------------------------------------------------------------------
class TestWeatherFetch:
    """Test weather API fetching."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.service = WeatherService(self.bus, self.config)

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_fetch_weather_success(self, mock_get):
        """Successful API call should return WeatherData."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.service.fetch_weather()

        assert result is not None
        assert result.temperature == 72.5
        assert result.condition == "clear sky"
        assert result.humidity == 45
        assert result.wind_speed == 5.2
        assert result.location == "New York"

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_fetch_weather_timeout_retries(self, mock_get):
        """On timeout, should retry once then return None."""
        import requests as req
        mock_get.side_effect = req.Timeout("Connection timed out")

        result = self.service.fetch_weather()

        assert result is None
        # Should have been called twice (initial + 1 retry)
        assert mock_get.call_count == 2

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_fetch_weather_http_error_no_retry(self, mock_get):
        """HTTP errors (like 401 bad key) should NOT retry."""
        import requests as req
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("401 Unauthorized")
        mock_get.return_value = mock_response

        result = self.service.fetch_weather()

        assert result is None
        # Should only be called once (no retry on HTTP errors)
        assert mock_get.call_count == 1

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_fetch_weather_retry_then_success(self, mock_get):
        """If first attempt times out but retry succeeds, return data."""
        import requests as req

        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None

        # First call times out, second succeeds
        mock_get.side_effect = [req.Timeout("timeout"), mock_response]

        result = self.service.fetch_weather()

        assert result is not None
        assert result.temperature == 72.5
        assert mock_get.call_count == 2

    # ------------------------------------------------------------------------------------------------
    def test_fetch_weather_no_api_key(self):
        """If API key is empty, should return None without making a request."""
        self.config.weather.api_key = ""

        result = self.service.fetch_weather()

        assert result is None

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_fetch_weather_malformed_response(self, mock_get):
        """If API response has unexpected format, return None."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"unexpected": "format"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.service.fetch_weather()

        assert result is None


# ----------------------------------------------------------------------------------------------------
class TestWeatherFormat:
    """Test announcement formatting."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.service = WeatherService(self.bus, self.config)

    # ------------------------------------------------------------------------------------------------
    def test_format_announcement_basic(self):
        """Should produce a natural-sounding weather announcement."""
        from datetime import datetime
        data = WeatherData(
            temperature=72.5,
            condition="clear sky",
            humidity=45,
            wind_speed=5.2,
            location="New York",
            timestamp=datetime.now(),
        )

        result = self.service.format_announcement(data)

        assert "72" in result  # Rounded from 72.5
        assert "clear sky" in result
        assert "45" in result
        assert "percent" in result

    # ------------------------------------------------------------------------------------------------
    def test_format_announcement_rounds_temperature(self):
        """Temperature should be rounded to nearest integer."""
        from datetime import datetime
        data = WeatherData(
            temperature=68.7,
            condition="rain",
            humidity=80,
            wind_speed=10.0,
            location="London",
            timestamp=datetime.now(),
        )

        result = self.service.format_announcement(data)

        assert "69" in result  # 68.7 rounds to 69
        assert "68.7" not in result  # Should NOT contain the decimal


# ----------------------------------------------------------------------------------------------------
class TestWeatherEvents:
    """Test event handling and cooldown."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config(cooldown=2)
        self.service = WeatherService(self.bus, self.config)

    def teardown_method(self):
        self.service.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_human_detected_triggers_fetch(self, mock_get):
        """'human_detected' event should trigger weather fetch and emit weather_ready."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.3)

        assert len(results) == 1
        assert "72" in results[0]["text"]
        assert "clear sky" in results[0]["text"]

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_command_weather_triggers_fetch(self, mock_get):
        """'command_weather' event should trigger weather fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        self.bus.emit("command_weather")
        time.sleep(0.3)

        assert len(results) == 1

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_cooldown_prevents_rapid_fetch(self, mock_get):
        """Multiple triggers within cooldown should only fetch once."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        # Trigger twice rapidly
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.2)
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.3)

        # Only one fetch should have happened
        assert len(results) == 1

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_voice_command_bypasses_cooldown(self, mock_get):
        """'command_weather' should bypass cooldown (user explicitly asked)."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        # First trigger via detection
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.2)
        # Immediately follow with voice command — should bypass cooldown
        self.bus.emit("command_weather")
        time.sleep(0.3)

        # Both should have fetched
        assert len(results) == 2

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_api_failure_emits_unavailable_message(self, mock_get):
        """If API fails, should emit 'Weather data is currently unavailable.'"""
        import requests as req
        mock_get.side_effect = req.Timeout("timeout")

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        self.bus.emit("command_weather")
        time.sleep(0.3)

        assert len(results) == 1
        assert "unavailable" in results[0]["text"].lower()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_events_ignored_after_stop(self, mock_get):
        """After stop(), events should not trigger fetches."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.service.start()
        self.service.stop()
        self.bus.emit("command_weather")
        time.sleep(0.2)

        assert len(results) == 0

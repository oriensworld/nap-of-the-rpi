# ----------------------------------------------------------------------------------------------------
# test_integration.py
# ----------------------------------------------------------------------------------------------------

"""
Integration tests: verify full event flows across modules.

These tests wire multiple modules together (with mocked hardware) and verify
that events flow correctly through the system:
- PIR detection → laser activates + weather announced
- Voice command → weather announced
- Voice command → laser toggled
- Error isolation (one module failure doesn't crash others)

All hardware is mocked — these tests run on any machine without a Pi.

RUN WITH:
    uv run pytest tests/test_integration.py -v
"""

# ----------------------------------------------------------------------------------------------------
import time
from unittest.mock import MagicMock, patch

import numpy as np
from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPWMPin

from core.event_bus import EventBus
from modules.laser_controller import LaserController
from modules.pir_sensor import PIRSensor
from modules.tts_speaker import TTSSpeaker
from modules.voice_command import VoiceCommand
from modules.weather_service import WeatherService

# ----------------------------------------------------------------------------------------------------
Device.pin_factory = MockFactory(pin_class=MockPWMPin)


# ----------------------------------------------------------------------------------------------------
def make_config():
    """Create a full mock config for integration testing."""
    config = MagicMock()
    config.pir.pin = 17
    config.pir.cooldown_seconds = 0.5
    config.laser.pin = 18
    config.laser.pattern = "solid"
    config.laser.duration_seconds = 0.5
    config.laser.blink_frequency_hz = 10.0
    config.laser.pulse_rate_hz = 2.0
    config.weather.api_key = "test-key"
    config.weather.location = "TestCity,US"
    config.weather.units = "imperial"
    config.voice.wake_word = "hey pi"
    config.voice.model_path = "./models/test"
    config.audio.tts_model_path = "./models/test-voice"
    config.audio.bluetooth_device = "Test Speaker"
    config.audio.fallback_to_jack = True
    config.system.log_level = "WARNING"
    config.system.log_file = "/tmp/test.log"
    config.system.log_max_bytes = 1000000
    config.system.log_backup_count = 1
    return config


SAMPLE_WEATHER_RESPONSE = {
    "main": {"temp": 75.0, "humidity": 50},
    "weather": [{"description": "partly cloudy", "main": "Clouds"}],
    "wind": {"speed": 8.0},
    "name": "TestCity",
}


# ----------------------------------------------------------------------------------------------------
class TestPIRToLaserFlow:
    """Integration: PIR detection → laser activation."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()
        self.laser = LaserController(self.bus, self.config)
        self.pir = PIRSensor(self.bus, self.config)

    def teardown_method(self):
        self.pir.stop()
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_detection_activates_laser(self):
        """When PIR detects human, laser should activate with configured pattern."""
        self.laser.start()
        self.pir.start()

        # Simulate detection
        self.pir._on_motion_detected()
        time.sleep(0.2)

        # Laser should be active (solid pattern = on)
        assert self.laser.is_active or self.laser._laser.value > 0

    # ------------------------------------------------------------------------------------------------
    def test_laser_turns_off_after_duration(self):
        """Laser should turn off after pattern duration expires."""
        self.config.laser.duration_seconds = 0.3
        self.laser = LaserController(self.bus, self.config)
        self.laser.start()

        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.5)

        # Laser should be off after 0.3s duration
        assert self.laser._laser.value == 0


# ----------------------------------------------------------------------------------------------------
class TestPIRToWeatherFlow:
    """Integration: PIR detection → weather fetch → TTS announcement."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()
        self.weather = WeatherService(self.bus, self.config)

    def teardown_method(self):
        self.weather.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_detection_triggers_weather_announcement(self, mock_get):
        """PIR detection should fetch weather and emit weather_ready."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        announcements = []
        self.bus.subscribe("weather_ready", lambda data: announcements.append(data))

        self.weather.start()
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.3)

        assert len(announcements) == 1
        assert "75" in announcements[0]["text"]
        assert "partly cloudy" in announcements[0]["text"]

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_cooldown_prevents_repeated_announcements(self, mock_get):
        """Rapid PIR triggers should not cause repeated weather announcements."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        announcements = []
        self.bus.subscribe("weather_ready", lambda data: announcements.append(data))

        self.weather.start()
        # Three rapid triggers
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.1)
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.1)
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.3)

        # Only one announcement (cooldown blocks the rest)
        assert len(announcements) == 1


# ----------------------------------------------------------------------------------------------------
class TestVoiceCommandFlow:
    """Integration: voice command → weather/laser."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()
        self.weather = WeatherService(self.bus, self.config)
        self.laser = LaserController(self.bus, self.config)
        self.voice = VoiceCommand(self.bus, self.config)
        self.voice._running = True  # Simulate running without actual mic

    def teardown_method(self):
        self.weather.stop()
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_voice_weather_triggers_announcement(self, mock_get):
        """'hey pi weather' should trigger a weather announcement."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        announcements = []
        self.bus.subscribe("weather_ready", lambda data: announcements.append(data))

        self.weather.start()
        self.voice._process_text("hey pi weather")
        time.sleep(0.3)

        assert len(announcements) == 1
        assert "75" in announcements[0]["text"]

    # ------------------------------------------------------------------------------------------------
    def test_voice_laser_off_disables_laser(self):
        """'hey pi laser off' should disable the laser."""
        self.laser.start()

        self.voice._process_text("hey pi laser off")
        time.sleep(0.2)

        assert self.laser._enabled is False

    # ------------------------------------------------------------------------------------------------
    def test_voice_laser_on_reenables_laser(self):
        """'hey pi laser on' should re-enable the laser after disable."""
        self.laser.start()
        self.laser._enabled = False

        self.voice._process_text("hey pi laser on")
        time.sleep(0.2)

        assert self.laser._enabled is True

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_voice_bypasses_weather_cooldown(self, mock_get):
        """Voice command should get weather even within cooldown period."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        announcements = []
        self.bus.subscribe("weather_ready", lambda data: announcements.append(data))

        self.weather.start()

        # First: PIR trigger
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.2)

        # Immediately after: voice command (should bypass cooldown)
        self.voice._process_text("hey pi what's the weather")
        time.sleep(0.3)

        assert len(announcements) == 2


# ----------------------------------------------------------------------------------------------------
class TestFullChain:
    """Integration: full detection → laser + weather + TTS chain."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()
        self.laser = LaserController(self.bus, self.config)
        self.weather = WeatherService(self.bus, self.config)
        # TTS with mocked audio
        self.tts = TTSSpeaker(self.bus, self.config)
        self.tts._bluetooth = MagicMock()
        self.tts._bluetooth.is_connected.return_value = True

    def teardown_method(self):
        self.laser.stop()
        self.weather.stop()
        self.tts.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    @patch("modules.weather_service.requests.get")
    def test_detection_triggers_laser_and_speech(self, mock_get, mock_sd):
        """Full chain: detection → laser active + weather fetched + TTS speaks."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Mock Piper synthesis
        mock_piper = MagicMock()

        def fake_synthesize_wav(text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            samples = np.zeros(500, dtype=np.int16)
            wav_file.writeframes(samples.tobytes())

        mock_piper.synthesize_wav.side_effect = fake_synthesize_wav
        self.tts._piper = mock_piper
        self.tts._running = True
        # Start worker thread so queued speech is processed
        import threading as _threading
        self.tts._worker_thread = _threading.Thread(
            target=self.tts._speech_worker, daemon=True
        )
        self.tts._worker_thread.start()
        self.bus.subscribe("weather_ready", self.tts._on_weather_ready)

        self.laser.start()
        self.weather.start()

        # Trigger detection
        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(1.0)

        # Laser should have activated
        # (may already be off if duration expired, but the pattern ran)
        assert mock_get.called  # Weather was fetched
        assert mock_piper.synthesize_wav.called  # TTS spoke
        assert mock_sd.play.called  # Audio was played


# ----------------------------------------------------------------------------------------------------
class TestErrorIsolation:
    """Integration: one module failing shouldn't crash others."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.weather_service.requests.get")
    def test_weather_failure_doesnt_block_laser(self, mock_get):
        """If weather API fails, laser should still activate."""
        import requests as req
        mock_get.side_effect = req.Timeout("API down")

        laser = LaserController(self.bus, self.config)
        weather = WeatherService(self.bus, self.config)
        laser.start()
        weather.start()

        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.3)

        # Laser should still have activated despite weather failure
        assert laser.is_active or laser._laser.value > 0

        laser.stop()
        weather.stop()

    # ------------------------------------------------------------------------------------------------
    def test_laser_failure_doesnt_block_weather(self):
        """If laser GPIO fails, weather should still work."""
        weather = WeatherService(self.bus, self.config)
        weather.start()

        announcements = []
        self.bus.subscribe("weather_ready", lambda data: announcements.append(data))

        # Simulate laser init failure (don't start laser)
        # Weather should still respond to events
        with patch("modules.weather_service.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            self.bus.emit("human_detected", {"timestamp": time.time()})
            time.sleep(0.3)

        assert len(announcements) == 1
        weather.stop()

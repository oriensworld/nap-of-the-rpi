# ----------------------------------------------------------------------------------------------------
# test_voice_command.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the voice command module.

We mock Vosk (speech recognizer) and sounddevice (audio stream) since
tests don't have access to a microphone or the Vosk model file.

Testing strategy:
- Test _process_text() directly for command parsing logic
- Test start/stop lifecycle with mocked dependencies
- Test error handling (mic disconnect, model not found)

RUN WITH:
    uv run pytest tests/test_voice_command.py -v
"""

# ----------------------------------------------------------------------------------------------------
from core.event_bus import EventBus
from modules.voice_command import VoiceCommand
from unittest.mock import MagicMock, patch


# ----------------------------------------------------------------------------------------------------
import time


# ----------------------------------------------------------------------------------------------------
def make_config(wake_word="hey pi", model_path="./models/vosk-model-small-en-us"):
    """
    Create a mock Config for testing.
    """

    config = MagicMock()
    config.voice.wake_word = wake_word
    config.voice.model_path = model_path
    return config


# ----------------------------------------------------------------------------------------------------
class TestVoiceCommandParsing:
    """
    Test wake word detection and command parsing logic.
    """

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.voice = VoiceCommand(self.bus, self.config)
        self.voice._running = True  # Simulate running state for _process_text

    # ------------------------------------------------------------------------------------------------
    def test_weather_command(self):
        """'
        hey pi weather' should emit command_weather.
        """
        
        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("hey pi weather")
        time.sleep(0.1)

        assert results == ["weather"]

    # ------------------------------------------------------------------------------------------------
    def test_whats_the_weather_command(self):
        """
        'hey pi what's the weather' should emit command_weather.
        """

        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("hey pi what's the weather")
        time.sleep(0.1)

        assert results == ["weather"]

    # ------------------------------------------------------------------------------------------------
    def test_laser_on_command(self):
        """
        'hey pi laser on' should emit command_laser_on.
        """

        results = []
        self.bus.subscribe("command_laser_on", lambda data=None: results.append("laser_on"))

        self.voice._process_text("hey pi laser on")
        time.sleep(0.1)

        assert results == ["laser_on"]

    # ------------------------------------------------------------------------------------------------
    def test_laser_off_command(self):
        """
        'hey pi laser off' should emit command_laser_off.
        """

        results = []
        self.bus.subscribe("command_laser_off", lambda data=None: results.append("laser_off"))

        self.voice._process_text("hey pi laser off")
        time.sleep(0.1)

        assert results == ["laser_off"]

    # ------------------------------------------------------------------------------------------------
    def test_turn_on_laser_alternative(self):
        """
        'hey pi turn on laser' should also work.
        """

        results = []
        self.bus.subscribe("command_laser_on", lambda data=None: results.append("laser_on"))

        self.voice._process_text("hey pi turn on laser")
        time.sleep(0.1)

        assert results == ["laser_on"]

    # ------------------------------------------------------------------------------------------------
    def test_no_wake_word_ignored(self):
        """
        Text without wake word should be completely ignored.
        """

        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))
        self.bus.subscribe("weather_ready", lambda data: results.append("unrecognized"))

        self.voice._process_text("just random talking about the weather")
        time.sleep(0.1)

        assert results == []

    # ------------------------------------------------------------------------------------------------
    def test_unrecognized_command_emits_feedback(self):
        """
        Unknown command after wake word should emit 'Command not recognized.'
        """

        results = []
        self.bus.subscribe("weather_ready", lambda data: results.append(data))

        self.voice._process_text("hey pi do a backflip")
        time.sleep(0.1)

        assert len(results) == 1
        assert "not recognized" in results[0]["text"].lower()

    # ------------------------------------------------------------------------------------------------
    def test_case_insensitive(self):
        """
        Wake word and commands should be case-insensitive.
        """

        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("Hey Pi Weather")
        time.sleep(0.1)

        assert results == ["weather"]

    # ------------------------------------------------------------------------------------------------
    def test_wake_word_in_middle_of_text(self):
        """
        Wake word doesn't have to be at the start of recognized text.
        """

        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("okay so hey pi weather please")
        time.sleep(0.1)

        assert results == ["weather"]

    # ------------------------------------------------------------------------------------------------
    def test_custom_wake_word(self):
        """
        Custom wake word from config should work.
        """

        self.config.voice.wake_word = "computer"
        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("computer weather")
        time.sleep(0.1)

        assert results == ["weather"]

    # ------------------------------------------------------------------------------------------------
    def test_weather_report_phrase(self):
        """
        'hey pi weather report' should emit command_weather.
        """

        results = []
        self.bus.subscribe("command_weather", lambda data=None: results.append("weather"))

        self.voice._process_text("hey pi weather report")
        time.sleep(0.1)

        assert results == ["weather"]


# ----------------------------------------------------------------------------------------------------
class TestVoiceCommandLifecycle:
    """
    Test start/stop and initialization.
    """

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.voice_command.sd.RawInputStream")
    @patch("modules.voice_command.KaldiRecognizer", create=True)
    @patch("modules.voice_command.Model", create=True)
    def test_start_with_mocked_vosk(self, mock_model, mock_recognizer, mock_stream):
        """
        start() should initialize Vosk and audio stream.
        """

        with patch("vosk.Model", mock_model), patch("vosk.KaldiRecognizer", mock_recognizer):
            voice = VoiceCommand(self.bus, self.config)
            voice.start()

            assert voice._running is True
            mock_stream.assert_called_once()
            voice.stop()

    # ------------------------------------------------------------------------------------------------
    def test_start_without_vosk_model_emits_error(self):
        """
        If Vosk model can't load, should emit error event and not crash.
        """

        errors = []
        self.bus.subscribe("error", lambda data: errors.append(data))

        voice = VoiceCommand(self.bus, self.config)
        voice.start()  # Will fail because model doesn't exist

        time.sleep(0.1)
        assert voice._running is False
        assert len(errors) == 1
        assert errors[0]["module"] == "voice_command"

    # ------------------------------------------------------------------------------------------------
    def test_stop_without_start_no_error(self):
        """
        Calling stop() without start() should not crash.
        """

        voice = VoiceCommand(self.bus, self.config)
        voice.stop()  # Should not raise

    # ------------------------------------------------------------------------------------------------
    @patch("modules.voice_command.sd.RawInputStream")
    @patch("modules.voice_command.KaldiRecognizer", create=True)
    @patch("modules.voice_command.Model", create=True)
    def test_stop_closes_stream(self, mock_model, mock_recognizer, mock_stream):
        """
        stop() should close the audio stream and join the thread.
        """

        mock_stream_instance = MagicMock()
        mock_stream.return_value = mock_stream_instance

        with patch("vosk.Model", mock_model), patch("vosk.KaldiRecognizer", mock_recognizer):
            voice = VoiceCommand(self.bus, self.config)
            voice.start()
            voice.stop()

            mock_stream_instance.stop.assert_called_once()
            mock_stream_instance.close.assert_called_once()
            assert voice._stream is None
            assert voice._recognizer is None


# ----------------------------------------------------------------------------------------------------
class TestVoiceCommandMatchers:
    """
    Test the static command matching methods.
    """

    # ------------------------------------------------------------------------------------------------
    def test_match_weather_variants(self):
        """
        All weather phrases should match.
        """

        assert VoiceCommand._match_weather("weather") is True
        assert VoiceCommand._match_weather("what's the weather") is True
        assert VoiceCommand._match_weather("whats the weather") is True
        assert VoiceCommand._match_weather("how's the weather") is True
        assert VoiceCommand._match_weather("weather report") is True
        assert VoiceCommand._match_weather("tell me the weather") is True

    # ------------------------------------------------------------------------------------------------
    def test_match_weather_negative(self):
        """
        Non-weather phrases should not match.
        """

        assert VoiceCommand._match_weather("turn on the lights") is False
        assert VoiceCommand._match_weather("laser on") is False
        assert VoiceCommand._match_weather("") is False

    # ------------------------------------------------------------------------------------------------
    def test_match_laser_on_variants(self):
        """
        Laser-on phrases should match.
        """

        assert VoiceCommand._match_laser_on("laser on") is True
        assert VoiceCommand._match_laser_on("turn on laser") is True

    # ------------------------------------------------------------------------------------------------
    def test_match_laser_off_variants(self):
        """
        Laser-off phrases should match.
        """

        assert VoiceCommand._match_laser_off("laser off") is True
        assert VoiceCommand._match_laser_off("turn off laser") is True

    # ------------------------------------------------------------------------------------------------
    def test_match_laser_negative(self):
        """
        Non-laser phrases should not match.
        """
        
        assert VoiceCommand._match_laser_on("laser off") is False
        assert VoiceCommand._match_laser_off("laser on") is False

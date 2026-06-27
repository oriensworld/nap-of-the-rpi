# ----------------------------------------------------------------------------------------------------
# test_tts_speaker.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the TTS speaker module.

Mocks Piper TTS synthesis and audio playback since we don't need real audio
in tests. Also mocks BluetoothHelper since bluetoothctl is Linux-only.

RUN WITH:
    uv run pytest tests/test_tts_speaker.py -v
"""

# ----------------------------------------------------------------------------------------------------
from core.event_bus import EventBus
from modules.tts_speaker import TTSSpeaker
from unittest.mock import MagicMock, patch


# ----------------------------------------------------------------------------------------------------
import time
import numpy as np


# ----------------------------------------------------------------------------------------------------
def make_config():
    """
    Create a mock Config for testing.
    """
    config = MagicMock()
    config.audio.tts_model_path = "./models/test-voice"
    config.audio.tts_speed = 150
    config.audio.bluetooth_device = "Test Speaker"
    config.audio.fallback_to_jack = True
    return config


# ----------------------------------------------------------------------------------------------------
class TestTTSSpeakerBasic:
    """
    Basic start/stop and lifecycle tests.
    """

    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.BluetoothHelper")
    @patch("modules.tts_speaker.PiperVoice", create=True)
    def test_start_sets_running(self, mock_piper_class, mock_bt):
        """
        After start(), the speaker should be running.
        """
        # Mock the PiperVoice.load import inside start()
        with patch("piper.PiperVoice") as mock_pv:
            mock_pv.load.return_value = MagicMock()
            speaker = TTSSpeaker(self.bus, self.config)
            speaker._bluetooth = MagicMock()
            speaker.start()
            assert speaker._running is True
            speaker.stop()

    # ------------------------------------------------------------------------------------------------
    def test_start_without_piper_model_continues(self):
        """
        If Piper model can't load, start() should still succeed (graceful degradation).
        """
        speaker = TTSSpeaker(self.bus, self.config)
        speaker._bluetooth = MagicMock()
        # Don't mock piper — it will fail to import/load, but start() shouldn't crash
        speaker.start()
        assert speaker._running is True
        assert speaker._piper is None  # Model failed to load
        speaker.stop()

    # ------------------------------------------------------------------------------------------------
    def test_stop_clears_running(self):
        """
        After stop(), the speaker should not be running.
        """
        speaker = TTSSpeaker(self.bus, self.config)
        speaker._bluetooth = MagicMock()
        speaker.start()
        speaker.stop()
        assert speaker._running is False
        assert speaker._piper is None


# ----------------------------------------------------------------------------------------------------
class TestTTSSpeakerSynthesize:
    """
    Test speech synthesis logic.
    """

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.speaker = TTSSpeaker(self.bus, self.config)
        self.speaker._bluetooth = MagicMock()
    
    # ------------------------------------------------------------------------------------------------
    def teardown_method(self):
        self.speaker.stop()

    # ------------------------------------------------------------------------------------------------
    def test_synthesize_returns_none_without_piper(self):
        """
        If Piper is not loaded, _synthesize should return None.
        """

        self.speaker._piper = None
        result = self.speaker._synthesize("hello")
        assert result is None

    # ------------------------------------------------------------------------------------------------
    def test_synthesize_returns_audio_array(self):
        """
        With a mocked Piper, _synthesize should return a numpy array.
        """

        # Create a mock Piper that writes valid WAV data via synthesize_wav
        mock_piper = MagicMock()

        def fake_synthesize_wav(text, wav_file):
            # synthesize_wav is responsible for setting WAV params and writing frames
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            samples = np.zeros(1000, dtype=np.int16)
            wav_file.writeframes(samples.tobytes())

        mock_piper.synthesize_wav.side_effect = fake_synthesize_wav
        self.speaker._piper = mock_piper
        self.speaker._running = True

        result = self.speaker._synthesize("test speech")

        assert result is not None
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        assert len(result) == 1000


# ----------------------------------------------------------------------------------------------------
class TestTTSSpeakerPlayback:
    """
    Test audio playback logic.
    """

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.speaker = TTSSpeaker(self.bus, self.config)
        self.speaker._bluetooth = MagicMock()
        self.speaker._bluetooth.is_connected.return_value = True

    # ------------------------------------------------------------------------------------------------
    def teardown_method(self):
        self.speaker.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_play_audio_calls_sounddevice(self, mock_sd):
        """
        _play_audio should call sd.play() with the audio data.
        """

        audio = np.zeros(1000, dtype=np.int16)
        self.speaker._running = True
        self.speaker._play_audio(audio)

        mock_sd.play.assert_called_once()
        mock_sd.wait.assert_called_once()
        # Verify the audio data was passed
        call_args = mock_sd.play.call_args
        np.testing.assert_array_equal(call_args[0][0], audio)

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_play_audio_bt_disconnected_fallback(self, mock_sd):
        """
        If BT is disconnected but fallback enabled, should still play.
        """

        self.speaker._bluetooth.is_connected.return_value = False
        self.speaker._running = True

        audio = np.zeros(1000, dtype=np.int16)
        self.speaker._play_audio(audio)

        # Should still play (via fallback to default output)
        mock_sd.play.assert_called_once()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_play_audio_bt_disconnected_no_fallback(self, mock_sd):
        """
        If BT is disconnected and fallback disabled, should NOT play.
        """

        self.speaker._bluetooth.is_connected.return_value = False
        self.config.audio.fallback_to_jack = False
        self.speaker._running = True

        audio = np.zeros(1000, dtype=np.int16)
        self.speaker._play_audio(audio)

        # Should NOT play
        mock_sd.play.assert_not_called()


# ----------------------------------------------------------------------------------------------------
class TestTTSSpeakerEvents:
    """
    Test event handling.
    """

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        self.bus = EventBus()
        self.config = make_config()
        self.speaker = TTSSpeaker(self.bus, self.config)
        self.speaker._bluetooth = MagicMock()
        self.speaker._bluetooth.is_connected.return_value = True

    # ------------------------------------------------------------------------------------------------
    def teardown_method(self):
        self.speaker.stop()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_weather_ready_triggers_speak(self, mock_sd):
        """
        'weather_ready' event should trigger speech synthesis and playback
        """

        # Set up a mock Piper that produces audio
        mock_piper = MagicMock()

        def fake_synthesize_wav(text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            samples = np.zeros(500, dtype=np.int16)
            wav_file.writeframes(samples.tobytes())

        mock_piper.synthesize_wav.side_effect = fake_synthesize_wav
        self.speaker._piper = mock_piper
        self.speaker._running = True
        self.bus.subscribe("weather_ready", self.speaker._on_weather_ready)

        # Emit event
        self.bus.emit("weather_ready", {"text": "It's 72 degrees"})
        time.sleep(0.5)

        # Piper should have been called
        mock_piper.synthesize_wav.assert_called_once()
        # Audio should have been played
        mock_sd.play.assert_called_once()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_events_ignored_after_stop(self, mock_sd):
        """
        After stop(), weather_ready events should not trigger speech.
        """

        mock_piper = MagicMock()
        self.speaker._piper = mock_piper
        self.speaker.start()
        self.speaker.stop()

        self.bus.emit("weather_ready", {"text": "should be ignored"})
        time.sleep(0.2)

        mock_piper.synthesize_wav.assert_not_called()

    # ------------------------------------------------------------------------------------------------
    @patch("modules.tts_speaker.sd")
    def test_empty_text_not_spoken(self, mock_sd):
        """
        Empty text in weather_ready should not trigger synthesis.
        """

        mock_piper = MagicMock()
        self.speaker._piper = mock_piper
        self.speaker._running = True

        self.speaker._on_weather_ready({"text": ""})
        time.sleep(0.2)

        mock_piper.synthesize_wav.assert_not_called()


# ----------------------------------------------------------------------------------------------------
class TestBluetoothHelper:
    """
    Test BluetoothHelper (mocked subprocess calls).
    """

    # ------------------------------------------------------------------------------------------------
    @patch("utils.bluetooth.platform.system", return_value="Windows")
    def test_is_connected_windows_returns_true(self, mock_platform):
        """
        On Windows (dev), is_connected() should return True.
        """

        from utils.bluetooth import BluetoothHelper
        bt = BluetoothHelper("Test Speaker")
        bt._is_linux = False
        assert bt.is_connected() is True

    # ------------------------------------------------------------------------------------------------
    @patch("utils.bluetooth.platform.system", return_value="Windows")
    def test_connect_windows_returns_true(self, mock_platform):
        """
        On Windows (dev), connect() should return True.
        """

        from utils.bluetooth import BluetoothHelper
        bt = BluetoothHelper("Test Speaker")
        bt._is_linux = False
        assert bt.connect() is True

    # ------------------------------------------------------------------------------------------------
    @patch("utils.bluetooth.subprocess.run")
    def test_is_connected_linux_checks_bluetoothctl(self, mock_run):
        """
        On Linux, should shell out to bluetoothctl to check status.
        """

        from utils.bluetooth import BluetoothHelper
        bt = BluetoothHelper("JBL Flip 6")
        bt._is_linux = True
        bt._mac_address = "AA:BB:CC:DD:EE:FF"

        mock_run.return_value = MagicMock(stdout="Connected: yes\n")

        assert bt.is_connected() is True

    # ------------------------------------------------------------------------------------------------
    @patch("utils.bluetooth.subprocess.run")
    def test_is_connected_linux_not_connected(self, mock_run):
        """
        If bluetoothctl shows not connected, should return False.
        """

        from utils.bluetooth import BluetoothHelper
        bt = BluetoothHelper("JBL Flip 6")
        bt._is_linux = True
        bt._mac_address = "AA:BB:CC:DD:EE:FF"

        mock_run.return_value = MagicMock(stdout="Connected: no\n")

        assert bt.is_connected() is False

    # ------------------------------------------------------------------------------------------------
    @patch("utils.bluetooth.subprocess.run")
    def test_ensure_connected_retries(self, mock_run):
        """
        ensure_connected should retry on failure.
        """
        
        from utils.bluetooth import BluetoothHelper
        bt = BluetoothHelper("JBL Flip 6")
        bt._is_linux = True
        bt._mac_address = "AA:BB:CC:DD:EE:FF"

        # First two calls: not connected (info check), failed connect
        # Third: connected
        mock_run.side_effect = [
            MagicMock(stdout="Connected: no\n"),  # is_connected check
            MagicMock(stdout="Failed\n"),          # connect attempt 1
            MagicMock(stdout="Connected: no\n"),   # is_connected check (in ensure_connected loop)
            MagicMock(stdout="Connection successful\n"),  # connect attempt 2
        ]

        result = bt.ensure_connected(retries=3, delay=0.1)
        assert result is True

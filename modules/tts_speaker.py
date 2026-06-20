# ----------------------------------------------------------------------------------------------------
# tts_speaker.py
# ----------------------------------------------------------------------------------------------------

"""
TTS speaker module: neural text-to-speech via Piper with Bluetooth output.

This module:
1. Subscribes to 'weather_ready' events (and any other events that carry text)
2. Synthesizes speech using Piper TTS (high-quality neural voice, runs offline)
3. Plays audio through the configured output (Bluetooth speaker or 3.5mm jack)
4. Handles Bluetooth connection with automatic fallback

Piper TTS:
- Produces natural-sounding speech (much better than robotic pyttsx3)
- Runs entirely offline — no internet needed after model download
- Optimized for Raspberry Pi (fast inference on ARM)
- Models are ~50-100MB, downloaded by setup.sh

Audio output chain:
    Text → Piper (synthesize WAV) → sounddevice (play through audio device)
"""

# ----------------------------------------------------------------------------------------------------
from utils.bluetooth import BluetoothHelper

# ----------------------------------------------------------------------------------------------------
import io
import logging
import numpy as np
import sounddevice as sd
import threading
import wave

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------------------------------
class TTSSpeaker:
    """
    Converts text to speech using Piper TTS and plays through Bluetooth speaker.

    Subscribes to:
    - 'weather_ready': speaks the weather announcement text

    The speak() method runs in a separate thread to avoid blocking the event bus.
    If Bluetooth is unavailable, falls back to 3.5mm jack (or default audio device).

    Usage:
        speaker = TTSSpeaker(event_bus, config)
        speaker.start()
        speaker.speak("Currently it's 72 degrees and clear sky.")
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self, event_bus, config):
        """
        Initialize the TTS speaker module.

        Args:
            event_bus: The EventBus instance for subscribing to events.
            config: The Config instance (uses config.audio.*).
        """
        self.event_bus = event_bus
        self.config = config
        self._running = False
        self._piper = None  # Piper voice synthesis instance
        self._bluetooth = BluetoothHelper(config.audio.bluetooth_device)
        self._speak_lock = threading.Lock()  # Prevent overlapping speech

    # ------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """
        Subscribe to events and initialize Piper TTS.

        Attempts to load the Piper voice model. If it fails (model not downloaded),
        logs an error but continues — speak() will emit error messages instead of crashing.
        """
        if self._running:
            logger.warning("TTS speaker already running")
            return

        # Try to initialize Piper TTS
        try:
            from piper import PiperVoice

            model_path = self.config.audio.tts_model_path
            self._piper = PiperVoice.load(model_path)
            logger.info(f"Piper TTS loaded from {model_path}")
        except Exception as e:
            logger.error(
                f"Failed to load Piper TTS: {e}. "
                f"Run setup.sh to download the voice model."
            )
            self._piper = None

        # Subscribe to events
        self.event_bus.subscribe("weather_ready", self._on_weather_ready)
        self._running = True

        # Try to connect Bluetooth speaker (non-blocking, best-effort)
        if self.config.audio.fallback_to_jack:
            # Don't block startup if BT isn't available
            threading.Thread(target=self._bluetooth.ensure_connected, daemon=True).start()

        logger.info("TTS speaker started")

    # ------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """Clean up audio resources."""
        self._running = False
        self.event_bus.unsubscribe("weather_ready", self._on_weather_ready)
        self._piper = None
        logger.info("TTS speaker stopped")

    # ------------------------------------------------------------------------------------------------
    def speak(self, text: str) -> None:
        """
        Synthesize and play speech for the given text.

        Runs synthesis + playback in a background thread to avoid blocking.
        Uses a lock to prevent overlapping speech (queues sequentially).

        Args:
            text: The text to speak aloud.
        """
        if not self._running:
            return

        # Run in background thread so event bus isn't blocked
        threading.Thread(
            target=self._speak_sync,
            args=(text,),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------------------------------------
    def _speak_sync(self, text: str) -> None:
        """
        Internal: synthesize and play speech synchronously.

        Called in a background thread. Uses a lock so that if multiple
        speak() calls happen rapidly, they play sequentially (not overlapping).
        """
        with self._speak_lock:
            try:
                audio_data = self._synthesize(text)
                if audio_data is not None:
                    self._play_audio(audio_data)
            except Exception as e:
                logger.error(f"TTS speak failed: {e}")

    # ------------------------------------------------------------------------------------------------
    def _synthesize(self, text: str) -> np.ndarray | None:
        """
        Synthesize text to audio using Piper TTS.

        Returns:
            Numpy array of audio samples (int16, mono), or None on failure.
        """
        if self._piper is None:
            logger.warning("Piper TTS not initialized — cannot synthesize")
            return None

        try:
            # Piper synthesizes to a WAV byte stream
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(22050)  # Piper's default sample rate
                self._piper.synthesize(text, wav_file)

            # Read back the WAV data as numpy array
            wav_buffer.seek(0)
            with wave.open(wav_buffer, "rb") as wav_file:
                frames = wav_file.readframes(wav_file.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)

            return audio_data

        except Exception as e:
            logger.error(f"Piper synthesis failed: {e}")
            return None

    # ------------------------------------------------------------------------------------------------
    def _play_audio(self, audio_data: np.ndarray, sample_rate: int = 22050) -> None:
        """
        Play audio data through the configured output device.

        Uses sounddevice which routes through the OS audio system.
        If Bluetooth is connected, audio goes to the BT speaker.
        If not, falls back to default output (3.5mm jack or USB audio).

        Args:
            audio_data: Numpy array of int16 audio samples.
            sample_rate: Sample rate in Hz (default 22050 for Piper).
        """
        try:
            # Ensure Bluetooth is connected (quick check, no long retry here)
            if not self._bluetooth.is_connected():
                if self.config.audio.fallback_to_jack:
                    logger.info("BT speaker not connected, using default audio output")
                else:
                    logger.warning("BT speaker not connected and fallback disabled")
                    return

            # Play audio and wait for it to finish
            sd.play(audio_data, samplerate=sample_rate)
            sd.wait()

        except Exception as e:
            logger.error(f"Audio playback failed: {e}")

    # ------------------------------------------------------------------------------------------------
    def _on_weather_ready(self, data: dict) -> None:
        """
        Event handler: speak the weather announcement.

        Args:
            data: Dict with 'text' key containing the announcement string.
        """
        if not self._running:
            return

        text = data.get("text", "")
        if text:
            logger.info(f"Speaking: {text[:50]}...")
            self.speak(text)

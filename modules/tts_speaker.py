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
import queue
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
    - 'tts_say': speaks arbitrary text from any module

    Speech requests are queued (FIFO) to prevent overlapping playback.
    Emits 'tts_speaking' when playback starts and 'tts_done' when finished.
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
        self._piper = None
        self._bluetooth = BluetoothHelper(config.audio.bluetooth_device)
        self._speak_lock = threading.Lock()
        self._queue = queue.Queue()
        self._worker_thread = None

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
        self.event_bus.subscribe("tts_say", self._on_tts_say)
        self._running = True

        # Start the speech worker thread (drains queue sequentially)
        self._worker_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self._worker_thread.start()

        # Try to connect Bluetooth speaker (non-blocking, best-effort)
        if self.config.audio.fallback_to_jack:
            threading.Thread(target=self._bluetooth.ensure_connected, daemon=True).start()

        logger.info("TTS speaker started")

    # ------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """Clean up audio resources."""
        self._running = False
        self.event_bus.unsubscribe("weather_ready", self._on_weather_ready)
        self.event_bus.unsubscribe("tts_say", self._on_tts_say)
        # Signal worker thread to exit
        self._queue.put(None)
        self._piper = None
        logger.info("TTS speaker stopped")

    # ------------------------------------------------------------------------------------------------
    def speak(self, text: str) -> None:
        """
        Queue text for speech synthesis and playback.

        Adds the text to a FIFO queue. The worker thread processes items sequentially.

        Args:
            text: The text to speak aloud.
        """
        if not self._running:
            return

        self._queue.put(text)

    # ------------------------------------------------------------------------------------------------
    def _speech_worker(self) -> None:
        """
        Background worker: drains the speech queue and speaks items in order.

        Runs until None is placed in the queue (signals shutdown).
        """
        while True:
            text = self._queue.get()
            if text is None:
                break
            self._speak_sync(text)

    # ------------------------------------------------------------------------------------------------
    def _speak_sync(self, text: str) -> None:
        """
        Internal: synthesize and play speech synchronously.

        Emits tts_speaking before playback and tts_done after (always, even on failure).
        Uses a lock so that if called from multiple paths, they play sequentially.
        """
        with self._speak_lock:
            try:
                audio_data = self._synthesize(text)
                if audio_data is not None:
                    self.event_bus.emit("tts_speaking", {"text": text})
                    self._play_audio(audio_data)
            except Exception as e:
                logger.error(f"TTS speak failed: {e}")
            finally:
                self.event_bus.emit("tts_done", {"text": text})

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
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                self._piper.synthesize_wav(text, wav_file)

            wav_buffer.seek(0)
            with wave.open(wav_buffer, "rb") as rf:
                frames = rf.readframes(rf.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)

            if len(audio_data) == 0:
                logger.warning("Piper produced empty audio")
                return None

            return audio_data

        except Exception as e:
            logger.error(f"Piper synthesis failed: {e}")
            return None

    # ------------------------------------------------------------------------------------------------
    def _play_audio(self, audio_data: np.ndarray, sample_rate: int = 22050) -> None:
        """
        Play audio data through the configured output device.

        Args:
            audio_data: Numpy array of int16 audio samples.
            sample_rate: Sample rate in Hz (default 22050 for Piper).
        """
        try:
            if not self._bluetooth.is_connected():
                if self.config.audio.fallback_to_jack:
                    logger.info("BT speaker not connected, using default audio output")
                else:
                    logger.warning("BT speaker not connected and fallback disabled")
                    return

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

    # ------------------------------------------------------------------------------------------------
    def _on_tts_say(self, data: dict) -> None:
        """
        Event handler: speak arbitrary text from any module.

        Args:
            data: Dict with 'text' key containing the text to speak.
        """
        if not self._running:
            return

        text = data.get("text", "")
        if text:
            logger.info(f"TTS say: {text[:50]}...")
            self.speak(text)

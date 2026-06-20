# ----------------------------------------------------------------------------------------------------
# voice_command.py
# ----------------------------------------------------------------------------------------------------

"""
Voice command module: wake word detection and command parsing via Vosk.

This module:
1. Opens a USB microphone audio stream via sounddevice
2. Runs continuous offline speech recognition using Vosk
3. Detects a configurable wake word (default: "hey pi")
4. Parses commands after the wake word and emits corresponding events
5. Handles mic disconnection gracefully

Vosk:
- Offline speech-to-text (no internet needed after model download)
- Low resource usage (~50MB RAM with small model)
- Real-time streaming recognition (processes audio as it arrives)
- Model: vosk-model-small-en-us (~40MB)

Supported commands (after wake word):
- "weather" / "what's the weather" → emits 'command_weather'
- "laser on"                       → emits 'command_laser_on'
- "laser off"                      → emits 'command_laser_off'
- Anything else                    → emits 'weather_ready' with "Command not recognized"
"""

# ----------------------------------------------------------------------------------------------------
import json
import logging
import queue
import threading

import sounddevice as sd

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------------
# Audio stream parameters for Vosk
SAMPLE_RATE = 16000  # Vosk expects 16kHz mono audio
BLOCK_SIZE = 8000    # Process 0.5 seconds of audio at a time
CHANNELS = 1         # Mono


# ----------------------------------------------------------------------------------------------------
class VoiceCommand:
    """
    Listens for wake word + commands via USB microphone using Vosk offline STT.

    Architecture:
    - A sounddevice InputStream feeds audio blocks into a queue
    - A background thread reads from the queue and feeds Vosk's recognizer
    - When text is recognized, it's checked for the wake word
    - If wake word found, the following text is parsed as a command

    Usage:
        voice = VoiceCommand(event_bus, config)
        voice.start()   # Begins listening in background
        # ... user says "hey pi weather" ...
        # → emits 'command_weather' event
        voice.stop()    # Stops listening, closes mic
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self, event_bus, config):
        """
        Initialize the voice command module.

        Args:
            event_bus: The EventBus instance for emitting command events.
            config: The Config instance (uses config.voice.* and config.audio.*).
        """
        self.event_bus = event_bus
        self.config = config

        # Internal state
        self._running = False
        self._recognizer = None      # Vosk KaldiRecognizer instance
        self._audio_queue: queue.Queue = queue.Queue()
        self._listen_thread: threading.Thread | None = None
        self._stream = None          # sounddevice InputStream

    # ------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """
        Begin continuous listening in background thread.

        Initializes Vosk model, opens audio stream, and starts the
        recognition loop in a daemon thread.
        """
        if self._running:
            logger.warning("Voice command already running")
            return

        try:
            # Initialize Vosk recognizer
            from vosk import KaldiRecognizer, Model

            model_path = self.config.voice.model_path
            model = Model(model_path)
            self._recognizer = KaldiRecognizer(model, SAMPLE_RATE)

            # Open microphone audio stream
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                dtype="int16",
                channels=CHANNELS,
                callback=self._audio_callback,
            )
            self._stream.start()

            # Start recognition loop in background
            self._running = True
            self._listen_thread = threading.Thread(
                target=self._recognition_loop,
                daemon=True,
            )
            self._listen_thread.start()

            logger.info(f"Voice command started (wake word: '{self.config.voice.wake_word}')")

        except Exception as e:
            logger.error(f"Failed to start voice command: {e}")
            self._running = False
            self.event_bus.emit("error", {
                "module": "voice_command",
                "message": f"Failed to initialize: {e}",
            })

    # ------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """
        Stop listening and close audio stream.

        Ensures the microphone is released and the recognition thread exits.
        """
        self._running = False

        # Stop audio stream
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self._stream = None

        # Wait for recognition thread to finish
        if self._listen_thread is not None:
            self._listen_thread.join(timeout=2.0)
            self._listen_thread = None

        self._recognizer = None
        logger.info("Voice command stopped")

    # ------------------------------------------------------------------------------------------------
    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """
        Callback from sounddevice: receives audio blocks from the microphone.

        This is called by sounddevice's internal thread whenever a new block
        of audio is available. We just put it in the queue for the recognition
        thread to process.

        Args:
            indata: Raw audio bytes (int16)
            frames: Number of frames in this block
            time_info: Timing information (unused)
            status: Stream status flags
        """
        if status:
            logger.debug(f"Audio stream status: {status}")
        # Put raw bytes into the queue (copy needed because indata buffer is reused)
        self._audio_queue.put(bytes(indata))

    # ------------------------------------------------------------------------------------------------
    def _recognition_loop(self) -> None:
        """
        Main recognition loop: reads audio from queue, feeds to Vosk.

        Runs in a background thread until self._running is False.
        When Vosk recognizes text, it's passed to _process_text().
        """
        logger.debug("Recognition loop started")

        while self._running:
            try:
                # Get audio data from queue (timeout allows checking _running flag)
                data = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._recognizer is None:
                break

            # Feed audio to Vosk
            # AcceptWaveform returns True when a complete utterance is recognized
            if self._recognizer.AcceptWaveform(data):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    self._process_text(text)
            else:
                # Partial result — we could use this for wake word detection
                # but full results are more reliable
                pass

        logger.debug("Recognition loop ended")

    # ------------------------------------------------------------------------------------------------
    def _process_text(self, text: str) -> None:
        """
        Process recognized text: check for wake word and parse commands.

        Flow:
        1. Check if the text contains the wake word
        2. If yes, extract the command portion (text after wake word)
        3. Match against known commands
        4. Emit the corresponding event

        Args:
            text: The full recognized text string (lowercase from Vosk).
        """
        wake_word = self.config.voice.wake_word.lower()
        text_lower = text.lower()

        # Check if wake word is in the recognized text
        if wake_word not in text_lower:
            return  # Not a command — ignore

        # Extract command portion (everything after the wake word)
        wake_idx = text_lower.index(wake_word) + len(wake_word)
        command = text_lower[wake_idx:].strip()

        logger.info(f"Wake word detected, command: '{command}'")

        # Match against known commands
        if self._match_weather(command):
            self.event_bus.emit("command_weather")
        elif self._match_laser_on(command):
            self.event_bus.emit("command_laser_on")
        elif self._match_laser_off(command):
            self.event_bus.emit("command_laser_off")
        else:
            # Unrecognized command — announce via TTS
            logger.info(f"Unrecognized command: '{command}'")
            self.event_bus.emit("weather_ready", {"text": "Command not recognized."})

    # ------------------------------------------------------------------------------------------------
    @staticmethod
    def _match_weather(command: str) -> bool:
        """Check if command matches weather request patterns."""
        weather_phrases = [
            "weather",
            "what's the weather",
            "whats the weather",
            "how's the weather",
            "hows the weather",
            "weather report",
            "tell me the weather",
        ]
        return any(phrase in command for phrase in weather_phrases)

    # ------------------------------------------------------------------------------------------------
    @staticmethod
    def _match_laser_on(command: str) -> bool:
        """Check if command matches laser-on patterns."""
        return "laser on" in command or "turn on laser" in command

    # ------------------------------------------------------------------------------------------------
    @staticmethod
    def _match_laser_off(command: str) -> bool:
        """Check if command matches laser-off patterns."""
        return "laser off" in command or "turn off laser" in command

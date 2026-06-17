"""nap-of-the-rpi: Raspberry Pi 4 human detection, laser trigger, and weather TTS system."""

import signal
import sys

from core.config import Config
from core.event_bus import EventBus


def main():
    """Entry point: load config, create event bus, wire modules, and run."""
    config = Config.load("config.yaml")
    event_bus = EventBus()

    # Module imports (deferred to avoid import errors on non-Pi machines)
    from modules.laser_controller import LaserController
    from modules.pir_sensor import PIRSensor
    from modules.tts_speaker import TTSSpeaker
    from modules.voice_command import VoiceCommand
    from modules.weather_service import WeatherService

    # Instantiate modules
    pir = PIRSensor(event_bus, config)
    laser = LaserController(event_bus, config)
    weather = WeatherService(event_bus, config)
    tts = TTSSpeaker(event_bus, config)
    voice = VoiceCommand(event_bus, config)

    modules = [pir, laser, weather, tts, voice]

    # Graceful shutdown handler
    def shutdown(signum, frame):
        print("\nShutting down...")
        for module in modules:
            module.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start all modules
    for module in modules:
        module.start()

    print("nap-of-the-rpi is running. Press Ctrl+C to stop.")

    # Keep main thread alive
    signal.pause()


if __name__ == "__main__":
    main()

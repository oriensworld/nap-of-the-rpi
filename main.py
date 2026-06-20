# ----------------------------------------------------------------------------------------------------
# main.py
# ----------------------------------------------------------------------------------------------------

"""
nap-of-the-rpi: Raspberry Pi 4 human detection, laser trigger, and weather TTS system.

This is the application entry point. It:
1. Loads configuration from config.yaml
2. Sets up logging (rotating file + console)
3. Creates the event bus (communication backbone)
4. Instantiates and starts all modules
5. Handles graceful shutdown (SIGTERM/SIGINT)
6. Sends systemd watchdog notifications (if running as a service)

Run directly:
    uv run python main.py

Run as systemd service:
    sudo bash scripts/install_service.sh
    sudo systemctl start nap-of-the-rpi
"""

# ----------------------------------------------------------------------------------------------------
import signal
import threading

from core.config import Config
from core.event_bus import EventBus
from utils.logger import get_logger, setup_logging


# ----------------------------------------------------------------------------------------------------
def main():
    """
    Entry point: load config, create event bus, wire modules, and run.

    Module start order matters:
    1. TTS speaker (so it's ready when weather announcements come)
    2. Weather service (subscribes to events)
    3. Laser controller (subscribes to events)
    4. Voice command (starts listening for commands)
    5. PIR sensor (starts detecting — triggers the whole chain)
    """
    # --- Load configuration ---
    config = Config.load("config.yaml")

    # --- Set up logging ---
    setup_logging(config)
    logger = get_logger("main")
    logger.info("nap-of-the-rpi starting up...")

    # --- Create event bus ---
    event_bus = EventBus()

    # --- Import modules (deferred to avoid import errors on non-Pi machines) ---
    from modules.laser_controller import LaserController
    from modules.pir_sensor import PIRSensor
    from modules.tts_speaker import TTSSpeaker
    from modules.voice_command import VoiceCommand
    from modules.weather_service import WeatherService

    # --- Instantiate modules ---
    tts = TTSSpeaker(event_bus, config)
    weather = WeatherService(event_bus, config)
    laser = LaserController(event_bus, config)
    voice = VoiceCommand(event_bus, config)
    pir = PIRSensor(event_bus, config)

    # Ordered list for start/stop (start order matters, stop is reversed)
    modules = [tts, weather, laser, voice, pir]

    # --- Shutdown flag ---
    shutdown_event = threading.Event()

    # --- Graceful shutdown handler ---
    def shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, shutting down...")

        # Stop modules in reverse order (PIR first so no new triggers)
        for module in reversed(modules):
            try:
                module.stop()
            except Exception as e:
                logger.error(f"Error stopping {module.__class__.__name__}: {e}")

        logger.info("All modules stopped. Goodbye!")
        shutdown_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # --- Start all modules ---
    for module in modules:
        try:
            module.start()
            logger.info(f"Started: {module.__class__.__name__}")
        except Exception as e:
            logger.error(f"Failed to start {module.__class__.__name__}: {e}")

    logger.info("nap-of-the-rpi is running. Press Ctrl+C to stop.")

    # --- Main loop with systemd watchdog ---
    # If running under systemd with WatchdogSec configured, we need to
    # periodically notify systemd that we're still alive. If we stop
    # notifying, systemd will restart us (assuming we're hung).
    watchdog_enabled = _is_watchdog_enabled()
    if watchdog_enabled:
        logger.info("Systemd watchdog enabled")

    while not shutdown_event.is_set():
        if watchdog_enabled:
            _notify_watchdog()
        # Sleep in short intervals so we respond quickly to shutdown signals
        shutdown_event.wait(timeout=10.0)


# ----------------------------------------------------------------------------------------------------
def _is_watchdog_enabled() -> bool:
    """
    Check if systemd watchdog is enabled for this service.

    Returns True if the WATCHDOG_USEC environment variable is set
    (systemd sets this when WatchdogSec is configured in the unit file).
    """
    import os
    return "WATCHDOG_USEC" in os.environ


# ----------------------------------------------------------------------------------------------------
def _notify_watchdog() -> None:
    """
    Send watchdog notification to systemd.

    This tells systemd "I'm still alive." If we stop sending these,
    systemd will assume we've hung and restart the service.

    Uses sd_notify protocol via the NOTIFY_SOCKET environment variable.
    Falls back to a no-op if the socket isn't available.
    """
    import os
    import socket

    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return

    try:
        # Handle abstract socket (starts with @)
        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(notify_socket)
        sock.sendall(b"WATCHDOG=1")
        sock.close()
    except Exception:
        pass  # Watchdog notification is best-effort


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()

# ----------------------------------------------------------------------------------------------------
# pir_sensor.py
# ----------------------------------------------------------------------------------------------------

"""
PIR sensor module: detects nearby humans via HC-SR501 infrared sensor.

The HC-SR501 is a passive infrared (PIR) sensor that detects motion by sensing changes in infrared
radiation (body heat). When a human walks into its field of view (~3-7 meters, 120 degree cone), the
sensor outputs HIGH on its signal pin.

This module:
    1. Monitors the GPIO pin connected to the PIR sensor
    2. Emits 'human_detected' events via the event bus when motion is detected
    3. Emits 'human_left' events when motion stops
    4. Enforces a cooldown period to prevent rapid repeated triggers
    5. Handles sensor disconnect gracefully

Hardware wiring:
    HC-SR501 VCC  → Pi 5V
    HC-SR501 GND  → Pi GND
    HC-SR501 OUT  → Pi GPIO 17 (configurable)

Note:
    A passive infrared sensor (PIR sensor) is an electronic device that measures infrared (IR)
    radiation emitted by objects in its field of view. They are most commonly used in motion 
    detectors, including security alarms and automatic lighting systems.
"""

# ----------------------------------------------------------------------------------------------------
# gpiozero is a high-level GPIO library for Raspberry Pi.
# MotionSensor wraps a PIR sensor with built-in edge detection.
# When running on a non-Pi machine (like Windows), we use MockFactory for testing.
from gpiozero import MotionSensor

# ----------------------------------------------------------------------------------------------------
import logging
import time

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------------
class PIRSensor:
    """
    Monitors GPIO input from HC-SR501, emits detection events with cooldown.

    The sensor has two states:
    - Motion detected (GPIO HIGH) → emits 'human_detected'
    - No motion (GPIO LOW) → emits 'human_left'

    Cooldown prevents the system from triggering the laser + weather announcement
    every time the sensor briefly flickers. Without cooldown, walking past the sensor
    could trigger 5-10 events in rapid succession.

    Usage:
        sensor = PIRSensor(event_bus, config)
        sensor.start()   # Begins monitoring in background
        # ... later ...
        sensor.stop()    # Stops monitoring, cleans up
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self, event_bus, config):
        """
        Initialize the PIR sensor module.

        Args:
            event_bus: The EventBus instance for emitting detection events.
            config: The Config instance (uses config.pir.pin and config.pir.cooldown_seconds).
        """
        self.event_bus = event_bus
        self.config = config

        # Internal state
        self._sensor = None           # gpiozero MotionSensor instance (created on start)
        self._running = False         # Whether the sensor is actively monitoring
        self._last_trigger_time = 0.0  # Timestamp of last 'human_detected' emission
        self._is_detected = False     # Current detection state (for external queries)

    # ------------------------------------------------------------------------------------------------
    @property
    def is_detected(self) -> bool:
        """
        Whether a human is currently detected (read-only property).
        """
        return self._is_detected

    # ------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """
        Begin monitoring the PIR sensor.

        Creates a gpiozero MotionSensor on the configured GPIO pin and attaches
        callbacks for motion detected / motion stopped events. gpiozero handles
        the background threading for GPIO monitoring internally.
        """
        if self._running:
            logger.warning("PIR sensor already running")
            return

        pin = self.config.pir.pin

        try:
            # Create the motion sensor on the configured pin.
            # gpiozero.MotionSensor automatically:
            #   - Sets up the GPIO pin as input
            #   - Monitors for rising/falling edges in a background thread
            #   - Calls our callbacks when state changes
            self._sensor = MotionSensor(pin)

            # Attach callbacks — these are called by gpiozero's internal thread
            # when the sensor state changes
            self._sensor.when_motion = self._on_motion_detected
            self._sensor.when_no_motion = self._on_motion_stopped

            self._running = True
            logger.info(f"PIR sensor started on GPIO {pin}")

        except Exception as e:
            # If the sensor can't be initialized (wrong pin, not on Pi, hardware issue),
            # log the error and emit an error event so other modules know
            logger.error(f"Failed to start PIR sensor: {e}")
            self.event_bus.emit("error", {
                "module": "pir_sensor",
                "message": f"Failed to initialize: {e}",
            })

    # ------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """
        Stop monitoring and clean up GPIO resources.

        This is important to call on shutdown to release the GPIO pin
        so other processes can use it.
        """
        self._running = False

        if self._sensor is not None:
            try:
                # close() releases the GPIO pin and stops internal monitoring
                self._sensor.close()
            except Exception as e:
                logger.error(f"Error closing PIR sensor: {e}")
            self._sensor = None

        self._is_detected = False
        logger.info("PIR sensor stopped")

    # ------------------------------------------------------------------------------------------------
    def _on_motion_detected(self) -> None:
        """
        Callback fired by gpiozero when the PIR sensor goes HIGH (motion detected).

        Checks the cooldown timer before emitting an event. If we're within the
        cooldown period, the detection is acknowledged but no event is emitted
        (prevents rapid re-triggering of laser + weather).
        """
        if not self._running:
            return

        self._is_detected = True
        now = time.time()
        cooldown = self.config.pir.cooldown_seconds

        # Check if enough time has passed since the last trigger
        elapsed = now - self._last_trigger_time
        if elapsed < cooldown:
            logger.debug(
                f"Motion detected but within cooldown "
                f"({elapsed:.1f}s < {cooldown}s), skipping"
            )
            return

        # Cooldown has passed — emit the event and update the timer
        self._last_trigger_time = now
        logger.info("Human detected")
        self.event_bus.emit("human_detected", {"timestamp": now})

    # ------------------------------------------------------------------------------------------------
    def _on_motion_stopped(self) -> None:
        """
        Callback fired by gpiozero when the PIR sensor goes LOW (no motion).

        This means the person has left the detection range. We emit 'human_left'
        without any cooldown restriction (it's useful to know immediately when
        someone leaves).
        """
        if not self._running:
            return

        self._is_detected = False
        logger.info("Human left detection range")
        self.event_bus.emit("human_left", {"timestamp": time.time()})

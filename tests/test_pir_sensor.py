# ----------------------------------------------------------------------------------------------------
# test_pir_sensor.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the PIR sensor module.

We test two things:
1. Module logic (cooldown, event emission, error handling) — by calling callbacks directly
2. GPIO integration — by driving mock pins where reliable

Direct callback testing is preferred because:
- gpiozero's MockFactory behavior varies across platforms
- We want to test OUR logic, not gpiozero's internal edge detection
- It's faster and more deterministic

RUN WITH:
    uv run pytest tests/test_pir_sensor.py -v
"""

# ----------------------------------------------------------------------------------------------------
import time
from unittest.mock import MagicMock, patch

from gpiozero import Device
from gpiozero.pins.mock import MockFactory

from core.event_bus import EventBus
from modules.pir_sensor import PIRSensor

# ----------------------------------------------------------------------------------------------------
# Tell gpiozero to use mock pins instead of real GPIO hardware.
Device.pin_factory = MockFactory()


# ----------------------------------------------------------------------------------------------------
def make_config(cooldown: int = 10, pin: int = 17):
    """Create a mock Config object for testing."""
    config = MagicMock()
    config.pir.pin = pin
    config.pir.cooldown_seconds = cooldown
    return config


# ----------------------------------------------------------------------------------------------------
class TestPIRSensorBasic:
    """Basic PIR sensor start/stop and detection behavior."""

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        """Create fresh instances before each test."""
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config(cooldown=2)
        self.sensor = PIRSensor(self.bus, self.config)

    # ------------------------------------------------------------------------------------------------
    def teardown_method(self):
        """Ensure sensor is stopped after each test."""
        self.sensor.stop()

    # ------------------------------------------------------------------------------------------------
    def test_start_sets_running(self):
        """After start(), the sensor should be in running state."""
        self.sensor.start()
        assert self.sensor._running is True

    # ------------------------------------------------------------------------------------------------
    def test_stop_clears_running(self):
        """After stop(), the sensor should no longer be running."""
        self.sensor.start()
        self.sensor.stop()
        assert self.sensor._running is False
        assert self.sensor._sensor is None

    # ------------------------------------------------------------------------------------------------
    def test_start_twice_no_error(self):
        """Calling start() when already running should not crash."""
        self.sensor.start()
        self.sensor.start()
        assert self.sensor._running is True

    # ------------------------------------------------------------------------------------------------
    def test_stop_without_start_no_error(self):
        """Calling stop() without start() should not crash."""
        self.sensor.stop()

    # ------------------------------------------------------------------------------------------------
    def test_motion_detected_emits_event(self):
        """When motion is detected, 'human_detected' event should be emitted."""
        results = []
        self.bus.subscribe("human_detected", lambda data: results.append(data))

        self.sensor.start()
        # Directly invoke the callback (simulates what gpiozero does when pin goes HIGH)
        self.sensor._on_motion_detected()

        time.sleep(0.1)
        assert len(results) == 1
        assert "timestamp" in results[0]

    # ------------------------------------------------------------------------------------------------
    def test_motion_stopped_emits_event(self):
        """When motion stops, 'human_left' event should be emitted."""
        results = []
        self.bus.subscribe("human_left", lambda data: results.append(data))

        self.sensor.start()
        self.sensor._on_motion_stopped()

        time.sleep(0.1)
        assert len(results) == 1
        assert "timestamp" in results[0]

    # ------------------------------------------------------------------------------------------------
    def test_is_detected_property(self):
        """The is_detected property should reflect current detection state."""
        self.sensor.start()
        assert self.sensor.is_detected is False

        self.sensor._on_motion_detected()
        assert self.sensor.is_detected is True

        self.sensor._on_motion_stopped()
        assert self.sensor.is_detected is False


# ----------------------------------------------------------------------------------------------------
class TestPIRSensorCooldown:
    """Test cooldown behavior — prevents rapid re-triggering."""

    # ------------------------------------------------------------------------------------------------
    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config(cooldown=2)
        self.sensor = PIRSensor(self.bus, self.config)

    # ------------------------------------------------------------------------------------------------
    def teardown_method(self):
        self.sensor.stop()

    # ------------------------------------------------------------------------------------------------
    def test_cooldown_prevents_rapid_triggers(self):
        """Multiple motion events within cooldown should only emit once."""
        results = []
        self.bus.subscribe("human_detected", lambda data: results.append(data))

        self.sensor.start()

        # First trigger — should emit
        self.sensor._on_motion_detected()
        time.sleep(0.1)

        # Second trigger immediately — should be suppressed by cooldown
        self.sensor._on_motion_detected()
        time.sleep(0.1)

        # Third trigger — still within cooldown
        self.sensor._on_motion_detected()
        time.sleep(0.1)

        # Only one event should have been emitted
        assert len(results) == 1

    # ------------------------------------------------------------------------------------------------
    def test_cooldown_expires_allows_next_trigger(self):
        """After cooldown expires, the next motion should emit an event."""
        results = []
        self.bus.subscribe("human_detected", lambda data: results.append(data))

        # Use a very short cooldown for this test
        self.config.pir.cooldown_seconds = 0.3
        self.sensor = PIRSensor(self.bus, self.config)
        self.sensor.start()

        # First trigger
        self.sensor._on_motion_detected()
        time.sleep(0.1)

        # Wait for cooldown to expire
        time.sleep(0.4)

        # Second trigger — cooldown has passed, should emit
        self.sensor._on_motion_detected()
        time.sleep(0.1)

        assert len(results) == 2

    # ------------------------------------------------------------------------------------------------
    def test_human_left_has_no_cooldown(self):
        """'human_left' events should NOT be subject to cooldown."""
        results = []
        self.bus.subscribe("human_left", lambda data: results.append(data))

        self.sensor.start()

        # Rapid 'human_left' events — all should emit (no cooldown on leaving)
        self.sensor._on_motion_stopped()
        self.sensor._on_motion_stopped()
        self.sensor._on_motion_stopped()

        time.sleep(0.1)
        assert len(results) == 3


# ----------------------------------------------------------------------------------------------------
class TestPIRSensorErrorHandling:
    """Test graceful handling of hardware errors."""

    # ------------------------------------------------------------------------------------------------
    def test_invalid_pin_emits_error_event(self):
        """If the sensor can't initialize, an error event should be emitted."""
        Device.pin_factory.reset()
        bus = EventBus()
        errors = []
        bus.subscribe("error", lambda data: errors.append(data))

        config = make_config(pin=17)
        sensor = PIRSensor(bus, config)

        # Patch MotionSensor to simulate a hardware initialization failure
        with patch("modules.pir_sensor.MotionSensor", side_effect=Exception("GPIO error")):
            sensor.start()

        time.sleep(0.1)

        # Sensor should not be running
        assert sensor._running is False
        # Error event should have been emitted
        assert len(errors) == 1
        assert errors[0]["module"] == "pir_sensor"
        assert "GPIO error" in errors[0]["message"]

    # ------------------------------------------------------------------------------------------------
    def test_callbacks_ignored_after_stop(self):
        """Events should not be emitted after the sensor is stopped."""
        Device.pin_factory.reset()
        bus = EventBus()
        config = make_config(cooldown=0)
        sensor = PIRSensor(bus, config)

        results = []
        bus.subscribe("human_detected", lambda data: results.append(data))

        sensor.start()
        sensor.stop()

        # Manually call the callback (simulating a race condition)
        sensor._on_motion_detected()

        time.sleep(0.1)
        assert len(results) == 0

    # ------------------------------------------------------------------------------------------------
    def test_callbacks_ignored_before_start(self):
        """Events should not be emitted if sensor was never started."""
        Device.pin_factory.reset()
        bus = EventBus()
        config = make_config(cooldown=0)
        sensor = PIRSensor(bus, config)

        results = []
        bus.subscribe("human_detected", lambda data: results.append(data))

        # Call callback without ever calling start()
        sensor._on_motion_detected()

        time.sleep(0.1)
        assert len(results) == 0

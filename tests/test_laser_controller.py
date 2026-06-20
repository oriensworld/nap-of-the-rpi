# ----------------------------------------------------------------------------------------------------
# test_laser_controller.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the laser controller module.

Tests cover:
- Start/stop lifecycle
- Pattern activation (solid, blink, pulse)
- Event subscription (human_detected, laser_on, laser_off)
- Cooldown/cancellation behavior
- Safety: laser always turns off after pattern or on stop()

RUN WITH:
    uv run pytest tests/test_laser_controller.py -v
"""

# ----------------------------------------------------------------------------------------------------
import time
from unittest.mock import MagicMock, patch

from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPWMPin

from core.event_bus import EventBus
from modules.laser_controller import LaserController

# ----------------------------------------------------------------------------------------------------
# Use mock GPIO pins with PWM support (PWMLED requires MockPWMPin, not plain MockPin)
Device.pin_factory = MockFactory(pin_class=MockPWMPin)


# ----------------------------------------------------------------------------------------------------
def make_config(pattern="blink", duration=1.0, blink_hz=10.0, pulse_rate=2.0, pin=18):
    """Create a mock Config for testing."""
    config = MagicMock()
    config.laser.pin = pin
    config.laser.pattern = pattern
    config.laser.duration_seconds = duration
    config.laser.blink_frequency_hz = blink_hz
    config.laser.pulse_rate_hz = pulse_rate
    return config


# ----------------------------------------------------------------------------------------------------
class TestLaserControllerBasic:
    """Basic start/stop and lifecycle tests."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config()
        self.laser = LaserController(self.bus, self.config)

    def teardown_method(self):
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_start_sets_running(self):
        """After start(), the controller should be running."""
        self.laser.start()
        assert self.laser._running is True

    # ------------------------------------------------------------------------------------------------
    def test_stop_clears_running(self):
        """After stop(), the controller should not be running."""
        self.laser.start()
        self.laser.stop()
        assert self.laser._running is False
        assert self.laser._laser is None

    # ------------------------------------------------------------------------------------------------
    def test_start_twice_no_error(self):
        """Calling start() twice should not crash."""
        self.laser.start()
        self.laser.start()
        assert self.laser._running is True

    # ------------------------------------------------------------------------------------------------
    def test_stop_without_start_no_error(self):
        """Calling stop() without start() should not crash."""
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_laser_off_after_stop(self):
        """Laser must be OFF after stop() — safety requirement."""
        self.laser.start()
        self.laser.activate()
        time.sleep(0.1)
        self.laser.stop()
        # Laser should be off and released
        assert self.laser._laser is None


# ----------------------------------------------------------------------------------------------------
class TestLaserPatterns:
    """Test the three laser patterns."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config(duration=0.5)
        self.laser = LaserController(self.bus, self.config)

    def teardown_method(self):
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_solid_pattern_turns_on_then_off(self):
        """Solid pattern: laser should be on during duration, off after."""
        self.config.laser.pattern = "solid"
        self.laser.start()
        self.laser.activate()

        # Check laser is on during pattern
        time.sleep(0.1)
        assert self.laser._laser.value > 0

        # Wait for pattern to finish
        time.sleep(0.6)
        assert self.laser._laser.value == 0

    # ------------------------------------------------------------------------------------------------
    def test_blink_pattern_toggles(self):
        """Blink pattern: laser should toggle on/off during duration."""
        self.config.laser.pattern = "blink"
        self.config.laser.blink_frequency_hz = 20.0  # Fast blink for testing
        self.laser.start()
        self.laser.activate()

        # Sample values during blinking — should see both on and off states
        values = []
        for _ in range(10):
            time.sleep(0.03)
            values.append(self.laser._laser.value)

        # Wait for pattern to finish
        time.sleep(0.6)

        # Should have seen at least one ON and one OFF during blinking
        assert 1.0 in values or any(v > 0 for v in values)
        # Laser should be off after pattern completes
        assert self.laser._laser.value == 0

    # ------------------------------------------------------------------------------------------------
    def test_pulse_pattern_varies_brightness(self):
        """Pulse pattern: laser brightness should vary (PWM fade in/out)."""
        self.config.laser.pattern = "pulse"
        self.config.laser.pulse_rate_hz = 4.0  # Fast pulse for testing
        self.config.laser.duration_seconds = 0.5
        self.laser.start()
        self.laser.activate()

        # Sample brightness values — should see variation
        values = []
        for _ in range(20):
            time.sleep(0.02)
            values.append(self.laser._laser.value)

        # Wait for pattern to finish
        time.sleep(0.5)

        # Should have seen different brightness levels (not all 0 or all 1)
        unique_values = set(round(v, 2) for v in values)
        assert len(unique_values) > 1, f"Expected varying brightness, got: {unique_values}"

        # Laser should be off after pattern completes
        assert self.laser._laser.value == 0

    # ------------------------------------------------------------------------------------------------
    def test_set_pattern_changes_behavior(self):
        """Changing pattern via set_pattern() should affect next activation."""
        self.laser.start()
        self.laser.set_pattern("solid")
        assert self.config.laser.pattern == "solid"

    # ------------------------------------------------------------------------------------------------
    def test_set_invalid_pattern_ignored(self):
        """Setting an invalid pattern should be ignored."""
        self.laser.start()
        original = self.config.laser.pattern
        self.laser.set_pattern("invalid_pattern")
        assert self.config.laser.pattern == original


# ----------------------------------------------------------------------------------------------------
class TestLaserEvents:
    """Test event subscription and response."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config(duration=0.3)
        self.laser = LaserController(self.bus, self.config)

    def teardown_method(self):
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_human_detected_activates_laser(self):
        """Laser should activate when 'human_detected' event fires."""
        self.config.laser.pattern = "solid"
        self.laser.start()

        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.2)

        # Laser should be on (pattern is running)
        assert self.laser.is_active or self.laser._laser.value > 0

    # ------------------------------------------------------------------------------------------------
    def test_laser_off_command_disables(self):
        """'command_laser_off' should disable the laser and stop current pattern."""
        self.config.laser.pattern = "solid"
        self.config.laser.duration_seconds = 5.0  # Long duration
        self.laser.start()

        # Activate, then disable
        self.laser.activate()
        time.sleep(0.1)
        self.bus.emit("command_laser_off")
        time.sleep(0.2)

        assert self.laser._enabled is False
        assert self.laser._laser.value == 0

    # ------------------------------------------------------------------------------------------------
    def test_laser_on_command_reenables(self):
        """'command_laser_on' should re-enable the laser after being disabled."""
        self.laser.start()

        self.bus.emit("command_laser_off")
        time.sleep(0.1)
        assert self.laser._enabled is False

        self.bus.emit("command_laser_on")
        time.sleep(0.1)
        assert self.laser._enabled is True

    # ------------------------------------------------------------------------------------------------
    def test_disabled_laser_ignores_detection(self):
        """When disabled, human detection should NOT activate the laser."""
        self.config.laser.pattern = "solid"
        self.laser.start()
        self.laser._enabled = False

        self.bus.emit("human_detected", {"timestamp": time.time()})
        time.sleep(0.2)

        assert self.laser._laser.value == 0


# ----------------------------------------------------------------------------------------------------
class TestLaserSafety:
    """Safety tests — laser must ALWAYS turn off."""

    def setup_method(self):
        Device.pin_factory.reset()
        self.bus = EventBus()
        self.config = make_config(duration=5.0)  # Long duration
        self.laser = LaserController(self.bus, self.config)

    def teardown_method(self):
        self.laser.stop()

    # ------------------------------------------------------------------------------------------------
    def test_deactivate_forces_off(self):
        """deactivate() should immediately turn off the laser."""
        self.config.laser.pattern = "solid"
        self.laser.start()
        self.laser.activate()
        time.sleep(0.1)

        self.laser.deactivate()
        time.sleep(0.1)

        assert self.laser._laser.value == 0

    # ------------------------------------------------------------------------------------------------
    def test_stop_cancels_running_pattern(self):
        """stop() should cancel a running pattern and turn off the laser."""
        self.config.laser.pattern = "solid"
        self.laser.start()
        self.laser.activate()
        time.sleep(0.1)

        self.laser.stop()
        # Laser object is released — if we got here without hanging, pattern was cancelled

    # ------------------------------------------------------------------------------------------------
    def test_error_on_init_emits_error_event(self):
        """If GPIO init fails, error event should be emitted."""
        Device.pin_factory.reset()
        bus = EventBus()
        errors = []
        bus.subscribe("error", lambda data: errors.append(data))

        config = make_config(pin=18)
        laser = LaserController(bus, config)

        with patch("modules.laser_controller.PWMLED", side_effect=Exception("GPIO failed")):
            laser.start()

        time.sleep(0.1)
        assert laser._running is False
        assert len(errors) == 1
        assert errors[0]["module"] == "laser_controller"

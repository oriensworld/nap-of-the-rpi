# ----------------------------------------------------------------------------------------------------
# test_config.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the Config manager.

These tests verify:
- Loading a valid YAML config file
- Falling back to defaults when the file is missing
- Environment variable substitution (${VAR} patterns)
- Deep merging (file values override defaults, but unspecified keys are preserved)
- Nested attribute access (config.laser.pattern)

RUN WITH:
    uv run pytest tests/test_config.py -v
"""

# ----------------------------------------------------------------------------------------------------

from core.config import DEFAULTS, Config


# ----------------------------------------------------------------------------------------------------
class TestConfigLoad:
    """Test loading config from YAML files."""

    # ------------------------------------------------------------------------------------------------
    def test_load_valid_config(self, tmp_path):
        """Loading a valid YAML file should override defaults."""
        # tmp_path is a pytest fixture — it gives us a temporary directory that's
        # automatically cleaned up after the test. We write a test config file there.
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
pir:
  cooldown_seconds: 20

laser:
  pattern: "pulse"
  duration_seconds: 5.0

weather:
  location: "London,GB"
  units: "metric"
"""
        )

        config = Config.load(str(config_file))

        # Values from our file should override defaults
        assert config.pir.cooldown_seconds == 20
        assert config.laser.pattern == "pulse"
        assert config.laser.duration_seconds == 5.0
        assert config.weather.location == "London,GB"
        assert config.weather.units == "metric"

    # ------------------------------------------------------------------------------------------------
    def test_defaults_preserved_for_unspecified_keys(self, tmp_path):
        """Keys not in the YAML file should use default values."""
        config_file = tmp_path / "config.yaml"
        # Only specify laser pattern — everything else should be defaults
        config_file.write_text(
            """
laser:
  pattern: "solid"
"""
        )

        config = Config.load(str(config_file))

        # laser.pattern was overridden
        assert config.laser.pattern == "solid"
        # But laser.pin was NOT in the file, so it should be the default
        assert config.laser.pin == 18
        assert config.laser.blink_frequency_hz == 5.0
        # Other sections should be entirely defaults
        assert config.pir.pin == 17
        assert config.pir.cooldown_seconds == 10
        assert config.voice.wake_word == "hey pi"

    # ------------------------------------------------------------------------------------------------
    def test_missing_file_uses_all_defaults(self):
        """If the config file doesn't exist, ALL defaults should be used."""
        config = Config.load("/nonexistent/path/config.yaml")

        # Everything should match DEFAULTS
        assert config.pir.pin == DEFAULTS["pir"]["pin"]
        assert config.pir.cooldown_seconds == DEFAULTS["pir"]["cooldown_seconds"]
        assert config.laser.pin == DEFAULTS["laser"]["pin"]
        assert config.laser.pattern == DEFAULTS["laser"]["pattern"]
        assert config.weather.location == DEFAULTS["weather"]["location"]
        assert config.voice.wake_word == DEFAULTS["voice"]["wake_word"]
        assert config.audio.bluetooth_device == DEFAULTS["audio"]["bluetooth_device"]
        assert config.system.log_level == DEFAULTS["system"]["log_level"]

    # ------------------------------------------------------------------------------------------------
    def test_empty_file_uses_all_defaults(self, tmp_path):
        """An empty config file should behave the same as a missing file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        config = Config.load(str(config_file))

        assert config.pir.pin == 17
        assert config.laser.pattern == "blink"


# ----------------------------------------------------------------------------------------------------
class TestConfigEnvVars:
    """Test environment variable substitution."""

    # ------------------------------------------------------------------------------------------------
    def test_env_var_substitution(self, tmp_path, monkeypatch):
        """${ENV_VAR} patterns should be replaced with actual env var values.

        monkeypatch is a pytest fixture that lets us safely set/unset environment
        variables for the duration of this test only (automatically restored after).
        """
        # Set a fake API key in the environment
        monkeypatch.setenv("WEATHER_API_KEY", "my-secret-key-123")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
weather:
  api_key: "${WEATHER_API_KEY}"
  location: "Tokyo,JP"
"""
        )

        config = Config.load(str(config_file))

        # The ${WEATHER_API_KEY} pattern should be replaced with the env var value
        assert config.weather.api_key == "my-secret-key-123"
        # Regular strings should be unaffected
        assert config.weather.location == "Tokyo,JP"

    # ------------------------------------------------------------------------------------------------
    def test_missing_env_var_becomes_empty_string(self, tmp_path, monkeypatch):
        """If an env var doesn't exist, ${VAR} is replaced with empty string."""
        # Make sure this var definitely doesn't exist
        monkeypatch.delenv("TOTALLY_FAKE_VAR_12345", raising=False)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
weather:
  api_key: "${TOTALLY_FAKE_VAR_12345}"
"""
        )

        config = Config.load(str(config_file))

        # Missing env var → empty string (not the literal "${...}" text)
        assert config.weather.api_key == ""

    # ------------------------------------------------------------------------------------------------
    def test_env_var_in_middle_of_string(self, tmp_path, monkeypatch):
        """Env vars can appear anywhere in a string value, even mixed with other text."""
        monkeypatch.setenv("MY_CITY", "Paris")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
weather:
  location: "${MY_CITY},FR"
"""
        )

        config = Config.load(str(config_file))

        assert config.weather.location == "Paris,FR"


# ----------------------------------------------------------------------------------------------------
class TestConfigAccess:
    """Test attribute-style access patterns."""

    # ------------------------------------------------------------------------------------------------
    def test_nested_attribute_access(self):
        """All config sections should be accessible via dot notation."""
        config = Config.load("/nonexistent/path.yaml")  # Use defaults

        # These should all work without raising AttributeError
        assert isinstance(config.pir.pin, int)
        assert isinstance(config.laser.pattern, str)
        assert isinstance(config.weather.location, str)
        assert isinstance(config.voice.wake_word, str)
        assert isinstance(config.audio.tts_speed, int)
        assert isinstance(config.system.log_level, str)

    # ------------------------------------------------------------------------------------------------
    def test_boolean_values_preserved(self):
        """Boolean values in config should remain as booleans (not strings)."""
        config = Config.load("/nonexistent/path.yaml")

        # audio.fallback_to_jack is True in defaults
        assert config.audio.fallback_to_jack is True

    # ------------------------------------------------------------------------------------------------
    def test_numeric_values_preserved(self, tmp_path):
        """Integer and float values should keep their types."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
laser:
  pin: 25
  duration_seconds: 7.5
"""
        )

        config = Config.load(str(config_file))

        assert config.laser.pin == 25
        assert isinstance(config.laser.pin, int)
        assert config.laser.duration_seconds == 7.5
        assert isinstance(config.laser.duration_seconds, float)

    # ------------------------------------------------------------------------------------------------
    def test_repr_is_readable(self):
        """Config and ConfigSection should have useful string representations."""
        config = Config.load("/nonexistent/path.yaml")

        # Should not crash and should contain useful info
        repr_str = repr(config)
        assert "Config(" in repr_str

        repr_section = repr(config.laser)
        assert "ConfigSection(" in repr_section
